#-*- coding:utf-8 -*-

import pcap
import dpkt
import time
import json
import chardet
import sys
import re
import traceback
import concurrent.futures
from cacheout import Cache, LRUCache

class tcp_http_pcap():

	def __init__(self, work_queue, interface, custom_tag, return_deep_info, http_filter_json, cache_size, session_size, bpf_filter, timeout, debug):
		"""
		构造函数
		:param work_queue: 捕获资产数据消息发送队列
		:param interface: 捕获流量的网卡名
		:param custom_tag: 数据标签，用于区分不同的采集引擎
		:param return_deep_info: 是否处理更多信息，包括原始请求、响应头和正文
		:param http_filter_json: HTTP过滤器配置，支持按状态和内容类型过滤
		:param cache_size: 缓存的已处理数据条数，120秒内重复的数据将不会发送Syslog
		:param session_size: 缓存的HTTP/TCP会话数量，16秒未使用的会话将被自动清除
		:param bpf_filter: 数据包底层过滤器
		:param timeout: 采集程序的运行超时时间，默认为启动后1小时自动退出
		:param debug: 调试开关
		"""
		self.work_queue = work_queue
		self.debug = debug
		self.timeout = timeout
		self.bpf_filter = bpf_filter
		self.cache_size = cache_size
		self.session_size = session_size
		self.http_filter_json = http_filter_json
		self.return_deep_info = return_deep_info
		self.custom_tag = custom_tag
		self.interface = interface
		self.sniffer = pcap.pcap(self.interface, snaplen=65535, promisc=True, timeout_ms=self.timeout, immediate=False)
		self.sniffer.setfilter(self.bpf_filter)
		# if self.session_size:
		self.tcp_stream_cache = Cache(maxsize=self.session_size, ttl=30, timer=time.time, default=None)
		if self.cache_size:
			self.tcp_cache = LRUCache(maxsize=self.cache_size, ttl=120, timer=time.time, default=None)

	def run(self):
		"""
		入口函数
		"""
		for ts, pkt in self.sniffer:
			packet = self.pkt_decode(pkt)
			if not packet:
				continue

			cache_key = '{}:{}'.format(packet.src, packet.sport)
			# SYN & ACK

			if packet.flags == 0x12:
				if self.cache_size and self.tcp_cache.get(cache_key):
					continue
				self.tcp_stream_cache.set('S_{}'.format(packet.ack), packet.seq + 1)
			else:
				# C->S first packet
				next_seq = self.tcp_stream_cache.get('S_{}'.format(packet.seq))
				if next_seq:
					self.tcp_stream_cache.set('C_{}'.format(packet.ack), packet.data)
					self.tcp_stream_cache.delete(packet.seq)
					continue

				# S->C first packet
				send_data = self.tcp_stream_cache.get('C_{}'.format(packet.seq))
				if send_data:
					if send_data.find(b' HTTP/') != -1:
						request_dict = self.decode_request(send_data)
						response_dict = self.decode_response(packet.data)
						data = {
							'pro': 'HTTP',
							'tag': self.custom_tag,
							'ip': packet.src,
							'port': packet.sport,
							'method': request_dict['method'],
							'code': response_dict['status'],
							'type': response_dict['type'],
							'server': response_dict['server'],
							'header': response_dict['headers'],
							'url': request_dict['uri'],
							'body': response_dict['body']
						}
					else:
						data = {
							'pro': 'TCP',
							'tag': self.custom_tag,
							'ip': packet.src,
							'port': packet.sport,
							'data': packet.data.hex()
						}
					
					self.send_msg(data)
					self.tcp_stream_cache.delete('C_{}'.format(packet.seq))

					# 瞬时重复处理
					if self.cache_size:
						self.tcp_cache.set(cache_key, True)

		self.sniffer.close()

	def pkt_decode(self, pkt):
		packet = dpkt.ethernet.Ethernet(pkt)
		if isinstance(packet.data, dpkt.ip.IP) and isinstance(packet.data.data, dpkt.tcp.TCP):
			if packet.data.data.flags == 0x12 or \
				packet.data.data.flags in [0x10, 0x18, 0x19] and len(packet.data.data.data) > 0:
				tcp_pkt = packet.data.data
				tcp_pkt.src = self.ip_addr(packet.data.src)
				tcp_pkt.dst = self.ip_addr(packet.data.dst)
				return tcp_pkt
		
		return None

	def ip_addr(self, ip):
		return '%d.%d.%d.%d'%tuple(ip)

	def decode_request(self, data):
		data_str = str(data, 'utf-8', 'ignore')

		m = re.match(r'^([A-Z]+) +([^ ]+) +HTTP/\d+\.\d+?\r\n(.*?)\r\n\r\n(.*?)', data_str, re.S)
		if m:
			headers = m.group(3).strip()
			header_dict = self.parse_headers(headers)
			url = 'http://{}{}'.format(header_dict['Host'], m.group(2)) if 'Host' in header_dict else m.group(2)
			
			return {
				'method': m.group(1),
				'uri': url,
				'headers': headers,
				'body': m.group(4)
			}
		
		return None

	def decode_response(self, data):
		pos = data.find(b'\r\n\r\n')
		header_str = str(data[:pos] if pos > 0 else data, 'utf-8', 'ignore')
		body = data[pos+4:] if pos > 0 else b''
		m = re.match(r'^HTTP/(\d+\.\d+) (\d+)[^\r\n]*\r\n(.*?)$', header_str, re.S)
		if m:
			headers = m.group(3).strip()
			headers_dict = self.parse_headers(headers)
			content_type = '' if 'Content-Type' not in headers_dict else headers_dict['Content-Type']
			server = '' if 'Server' not in headers_dict else headers_dict['Server']
			return {
				'version': m.group(1),
				'status': m.group(2),
				'headers': headers,
				'type': content_type,
				'server': server,
				'body': self.decode_body(body, content_type)
			}
		
		return None

	def decode_body(self, data, content_type):
		content_type = content_type.lower() if content_type else ''
		if 'charset=gbk' in content_type or 'charset=gb2312' in content_type:
			return str(data, 'gbk', 'ignore')
		
		decode_data = str(data, 'utf-8', 'ignore')
		m = re.match(r'<meta[^>]+?charset=[\'"]?([a-z\d\-]+)[\'"]?', decode_data, re.I)
		if m:
			charset = m.group(1).lower()
			if chardet != 'utf-8':
				return str(data, charset, 'ignore')
			
			return decode_data

		result = chardet.detect(data)
		if result and 'encoding' in result and result['encoding']:
			if result['encoding'] != 'utf-8':
				return str(data, result['encoding'], 'ignore')

		return decode_data

	def parse_headers(self, data):
		headers = {}
		lines = data.split('\r\n')
		for _ in lines:
			pos = _.find(':')
			if pos > 0:
				headers[_[:pos]] = _[pos+1:].strip()
		return headers

	def send_msg(self, data):
		result = json.dumps(data)
		if self.debug:
			print(result)
		self.work_queue.put(result)
