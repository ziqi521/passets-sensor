#-*- coding:utf-8 -*-

import logging
import logging.handlers 
import os
import sys

# TASK_LOCK_FILE临时文件，判断程序是否正在运行
TASK_LOCK_FILE = sys.path[0]+'/passets_sensor.lock'
global_pid = os.getpid()
if 'win' in sys.platform:
	global_os_version = 'win'
else:
	global_os_version = 'lnx'

def print_log(msg):
	print(msg)

def check_lock():
	try:
		# print_log('[+] check_lock ...')
		if not os.path.isfile(TASK_LOCK_FILE):
			w_lock = open(TASK_LOCK_FILE, 'w')
			w_lock.write(str(global_pid))
			w_lock.close()
		else:
			w_lock = open(TASK_LOCK_FILE, 'r')
			pid_str = w_lock.readline().strip('\n')
			w_lock.close()
			# lnx 判断进程是否存在
			if global_os_version == 'lnx':
				p = os.popen('ps -A | grep "%s"' % pid_str)
				if pid_str and 'python' not in p.read():
					w_lock = open(TASK_LOCK_FILE, 'w')
					w_lock.write(str(global_pid))
					w_lock.close()
				else:
					print_log('[!] passets_sensor already running !')
					sys.exit()
			# win 判断进程是否存在
			else:
				p = os.popen('tasklist /FI "PID eq %s"' % pid_str)
				if pid_str and p.read().count('python') == 0:
					w_lock = open(TASK_LOCK_FILE, 'w')
					w_lock.write(str(global_pid))
					w_lock.close()
				else:
					print_log('[!] passets_sensor already running !')
					sys.exit()
	except Exception as e:
		print_log('[!] check_lock Error !')
		print_log(e)
		sys.exit()

# 日志记录 
class _logging:
	def __init__(self,syslog_ip,syslog_port):

		self.syslog_ip = syslog_ip
		self.syslog_port = syslog_port
		self.logger = logging.getLogger()
		hdlr = logging.handlers.SysLogHandler((self.syslog_ip, self.syslog_port), logging.handlers.SysLogHandler.LOG_AUTH)
		# hdlr = logging.handlers.RotatingFileHandler(logfile, maxBytes=5242880, backupCount=5)
		formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
		hdlr.setFormatter(formatter)
		self.logger.addHandler(hdlr)
		self.logger.setLevel(logging.INFO)

	def info(self, msg):
		self.logger.info(msg)

	def warning(self, msg):
		self.logger.warning(msg)

	def error(self, msg):
		self.logger.error(msg)

	def exception(self, msg):
		self.logger.exception(msg)

	def critical(self, msg):
		self.logger.critical(msg)