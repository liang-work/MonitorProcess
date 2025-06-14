import psutil
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject, Signal, QThread, QElapsedTimer
from constants import MAX_MONITOR_PROCESSES

# 全局NVML状态
GLOBAL_HAS_NVML = False
GLOBAL_NVML_INITIALIZED = False

try:
    import pynvml
    GLOBAL_HAS_NVML = True
    logging.info("找到pynvml库，尝试初始化NVML")
    try:
        pynvml.nvmlInit()
        GLOBAL_NVML_INITIALIZED = True
        logging.info("NVML初始化成功")
    except pynvml.NVMLError as err:
        logging.warning(f"NVML初始化失败: {err}")
except ImportError:
    logging.warning("未找到pynvml库，GPU监控功能不可用")

class ProcessWorker(QObject):
    update_process = Signal(list)
    update_monitor = Signal(list)
    update_gpu = Signal(list)
    update_gpu_device = Signal(list)  # 新增GPU设备信息信号
    performance_stats = Signal(dict)

    def __init__(self):
        super().__init__()
        logging.info("初始化工作线程")
        self._is_running = True
        self._monitored_pids = []
        self._list_refresh_interval = 2000
        self._monitor_refresh_interval = 100
        self._gpu_refresh_interval = 1000
        self._last_selected_pids = set()
        self._last_cpu_times = {}
        self._last_cpu_percent = {}
        self._last_disk_io = {}
        self._last_net_io = {}
        self._executor = ThreadPoolExecutor(max_workers=4)  # 立即初始化线程池
        self._timer = QElapsedTimer()
        self._gpu_devices = []
        self._last_gpu_info = {}  # GPU信息缓存
        self._last_gpu_update_time = 0
        
        if GLOBAL_NVML_INITIALIZED:
            self._init_gpu_devices()
        
        self._init_executor()

    def _init_executor(self):
        """初始化线程池执行器"""
        if self._executor is None or getattr(self._executor, '_shutdown', True):
            self._executor = ThreadPoolExecutor(max_workers=4)
            logging.info("线程池执行器已初始化")

    def _init_gpu_devices(self):
        """初始化GPU设备信息"""
        try:
            device_count = pynvml.nvmlDeviceGetCount()
            self._gpu_devices = []
            for i in range(device_count):
                try:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                    name = pynvml.nvmlDeviceGetName(handle)
                    self._gpu_devices.append({
                        'handle': handle,
                        'name': name.decode('utf-8') if isinstance(name, bytes) else str(name),
                        'index': i
                    })
                    logging.info(f"检测到GPU设备 {i}: {name}")
                except pynvml.NVMLError as err:
                    logging.error(f"获取GPU设备{i}信息时出错: {err}")
        except pynvml.NVMLError as err:
            logging.error(f"获取GPU数量时出错: {err}")

    def _get_monitor_info(self, pid):
        """获取被监视进程的详细信息"""
        try:
            p = psutil.Process(pid)
            current_time = time.time()
            
            # 磁盘IO
            disk_io = p.io_counters()
            
            # 网络IO
            net_io = self._get_network_io_windows(pid)
            net_recv = net_io['bytes_recv']
            net_sent = net_io['bytes_sent']
            
            # 计算速度
            disk_read_speed = self._calculate_io_speed(
                pid, 'disk_read', disk_io.read_bytes, current_time, self._last_disk_io)
            disk_write_speed = self._calculate_io_speed(
                pid, 'disk_write', disk_io.write_bytes, current_time, self._last_disk_io)
            upload_speed = self._calculate_io_speed(
                pid, 'net_sent', net_sent, current_time, self._last_net_io)
            download_speed = self._calculate_io_speed(
                pid, 'net_recv', net_recv, current_time, self._last_net_io)
            
            # GPU信息
            gpu_usage, gpu_memory = 0, 0
            if GLOBAL_HAS_NVML:
                gpu_info = self._get_process_gpu_info(pid)
                gpu_usage = gpu_info['gpu_usage']
                gpu_memory = gpu_info['gpu_memory']
            
            return {
                'pid': pid,
                'name': p.name(),
                'cpu': self._calculate_cpu_percent(pid),
                'memory_working_set': p.memory_info().rss,
                'memory_commit': p.memory_info().vms,
                'memory_private': p.memory_full_info().private,
                'memory_percent': p.memory_percent(),
                'io_read': disk_io.read_bytes,
                'io_write': disk_io.write_bytes,
                'io_read_speed': disk_read_speed,
                'io_write_speed': disk_write_speed,
                'net_bytes_recv': net_recv,
                'net_bytes_sent': net_sent,
                'upload_speed': upload_speed,
                'download_speed': download_speed,
                'gpu_usage': gpu_usage,
                'gpu_memory': gpu_memory
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied) as err:
            logging.debug(f"获取监视进程{pid}信息时出错: {err}")
            return None
        
    def _get_network_io_windows(self, pid):
        """Windows系统下获取进程网络IO"""
        try:
            connections = psutil.net_connections()
            recv = sent = 0
            
            for conn in connections:
                if conn.pid == pid and conn.status == 'ESTABLISHED':
                    recv += getattr(conn, 'bytes_recv', 0)
                    sent += getattr(conn, 'bytes_sent', 0)
            
            return {'bytes_recv': recv, 'bytes_sent': sent}
        except Exception as e:
            logging.warning(f"获取进程 {pid} 网络 IO 时出错: {e}")
            return {'bytes_recv': 0, 'bytes_sent': 0}

    def _get_process_gpu_info(self, pid):
        """获取进程的GPU使用信息"""
        if not GLOBAL_NVML_INITIALIZED:
            return {'gpu_usage': 0, 'gpu_memory': 0}
        
        current_time = time.time()
        # 如果缓存未过期(1秒内)，使用缓存
        if pid in self._last_gpu_info and (current_time - self._last_gpu_info[pid]['timestamp']) < 1.0:
            return self._last_gpu_info[pid]['data']
        
        gpu_usage = 0
        gpu_memory = 0
        
        try:
            for device in self._gpu_devices:
                try:
                    processes = pynvml.nvmlDeviceGetComputeRunningProcesses(device['handle'])
                    for proc in processes:
                        if proc.pid == pid:
                            util = pynvml.nvmlDeviceGetUtilizationRates(device['handle'])
                            gpu_usage = max(gpu_usage, util.gpu)
                            
                            if proc.usedGpuMemory is not None:
                                gpu_memory += proc.usedGpuMemory // (1024 * 1024)
                except pynvml.NVMLError as err:
                    logging.debug(f"获取GPU进程信息时出错: {err}")
                    continue
        
            # 更新缓存
            self._last_gpu_info[pid] = {
                'data': {'gpu_usage': gpu_usage, 'gpu_memory': gpu_memory},
                'timestamp': current_time
            }
            
        except Exception as e:
            logging.warning(f"获取进程GPU信息时出错: {e}")
            return {'gpu_usage': 0, 'gpu_memory': 0}
        
        return {'gpu_usage': gpu_usage, 'gpu_memory': gpu_memory}

    def _calculate_io_speed(self, pid, io_type, current_value, current_time, last_io_dict):
        """计算IO速度"""
        key = f"{pid}_{io_type}"
        
        if key in last_io_dict:
            last_value, last_time = last_io_dict[key]
            time_diff = current_time - last_time
            if time_diff > 0:
                speed = (current_value - last_value) / time_diff
            else:
                speed = 0
        else:
            speed = 0
            
        last_io_dict[key] = (current_value, current_time)
        return speed

    def _get_process_info(self, proc):
        """获取进程基本信息（包含网络IO数据）"""
        try:
            info = proc.info
            pid = info['pid']
            
            # 获取磁盘IO
            io_info = proc.io_counters()
            
            # 获取网络IO（兼容不同平台）
            net_recv = 0
            net_sent = 0
            try:
                connections = proc.connections()
                for conn in connections:
                    if conn.status == 'ESTABLISHED':
                        net_recv += getattr(conn, 'bytes_recv', 0)
                        net_sent += getattr(conn, 'bytes_sent', 0)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            
            # 获取GPU信息
            gpu_info = self._get_process_gpu_info(pid)
            
            return {
                'pid': pid,
                'name': info['name'],
                'status': info['status'],
                'cpu': proc.cpu_percent(interval=0),
                'memory': info['memory_info'].rss,
                'memory_commit': info['memory_info'].vms,
                'memory_percent': info['memory_percent'],
                'threads': info['num_threads'],
                'io_read': io_info.read_bytes,
                'io_write': io_info.write_bytes,
                'net_bytes_recv': net_recv,  # 确保始终包含这个键
                'net_bytes_sent': net_sent,  # 确保始终包含这个键
                'gpu_usage': gpu_info['gpu_usage'],
                'gpu_memory': gpu_info['gpu_memory'],
                'selected': pid in self._last_selected_pids
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied) as err:
            logging.debug(f"获取进程信息时出错: {err}")
            return None

    def refresh_processes(self):
        """刷新进程列表数据（确保线程池可用）"""
        if not hasattr(self, '_executor') or self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=4)
            
        self._timer.start()
        try:
            processes = []
            current_pids = set()
            
            futures = []
            for proc in psutil.process_iter(['pid', 'name', 'status', 'memory_info', 'num_threads', 'memory_percent']):
                try:
                    if hasattr(self, '_executor') and self._executor is not None:
                        futures.append(self._executor.submit(self._get_process_info, proc))
                except RuntimeError as e:
                    logging.error(f"提交任务到线程池失败: {e}")
                    continue
            
            for future in futures:
                try:
                    result = future.result()
                    if result:
                        processes.append(result)
                        current_pids.add(result['pid'])
                except Exception as e:
                    logging.error(f"获取进程结果时出错: {e}")
                    continue
            
            self._last_selected_pids.intersection_update(current_pids)
            self.update_process.emit(processes)
            
            elapsed = self._timer.elapsed()
            self.performance_stats.emit({
                'process_count': len(processes),
                'process_time': elapsed
            })
            
            logging.debug(f"刷新进程列表，共 {len(processes)} 个进程，耗时 {elapsed}ms")
        except Exception as e:
            logging.error(f"刷新进程列表时出错: {e}")
            raise
        finally:
            # 确保即使出错也发送空列表保持UI响应
            if not processes:
                self.update_process.emit([])

    def refresh_monitored(self):
        """刷新被监视进程数据"""
        if not self._monitored_pids:
            return
            
        self._init_executor()  # 确保执行器可用
        self._timer.start()
        try:
            futures = []
            for pid in self._monitored_pids:
                try:
                    futures.append(self._executor.submit(self._get_monitor_info, pid))
                except RuntimeError as e:
                    if "cannot schedule new futures after shutdown" in str(e):
                        logging.warning("线程池已关闭，重新初始化...")
                        self._init_executor()
                        futures.append(self._executor.submit(self._get_monitor_info, pid))
                    else:
                        raise
            
            results = []
            for future in futures:
                result = future.result()
                if result:
                    results.append(result)
            
            self.update_monitor.emit(results)
            
            elapsed = self._timer.elapsed()
            self.performance_stats.emit({
                'monitor_count': len(results),
                'monitor_time': elapsed
            })
            
            logging.debug(f"刷新监视数据，共 {len(results)} 个被监视进程，耗时 {elapsed}ms")
        except Exception as e:
            logging.error(f"刷新监视数据时出错: {e}")
            raise

    def refresh_gpu_info(self):
        """合并GPU设备信息和进程信息查询"""
        if not GLOBAL_NVML_INITIALIZED:
            self.update_gpu.emit([])
            return
            
        self._timer.start()
        try:
            gpu_info = []
            current_time = time.time()
            
            for device in self._gpu_devices:
                try:
                    handle = device['handle']
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    
                    # 获取GPU进程信息
                    processes = []
                    try:
                        gpu_procs = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                        for proc in gpu_procs:
                            try:
                                p = psutil.Process(proc.pid)
                                processes.append({
                                    'pid': proc.pid,
                                    'name': p.name(),
                                    'gpu_usage': util.gpu,
                                    'gpu_memory': proc.usedGpuMemory // (1024 * 1024) if proc.usedGpuMemory else 0,
                                    'timestamp': current_time
                                })
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                continue
                    except pynvml.NVMLError as err:
                        logging.debug(f"获取GPU进程时出错: {err}")
                    
                    gpu_info.append({
                        'id': device['index'],
                        'name': device['name'],
                        'load': util.gpu,
                        'memory_used': mem_info.used // (1024 * 1024),
                        'memory_total': mem_info.total // (1024 * 1024),
                        'processes': processes,
                        'timestamp': current_time
                    })
                    
                except pynvml.NVMLError as err:
                    logging.error(f"查询GPU设备{device['index']}时出错: {err}")
                    continue
            
            self._last_gpu_update_time = current_time
            self.update_gpu.emit(gpu_info)
            
            elapsed = self._timer.elapsed()
            self.performance_stats.emit({
                'gpu_count': len(gpu_info),
                'gpu_time': elapsed
            })
            
        except Exception as e:
            logging.error(f"刷新GPU信息时出错: {e}")
            self.update_gpu.emit([])

    def refresh_gpu_device_info(self):
        """刷新GPU设备整体信息"""
        if not GLOBAL_NVML_INITIALIZED:
            self.update_gpu_device.emit([])
            return
        
        self._timer.start()
        try:
            gpu_device_info = []
            for device in self._gpu_devices:
                try:
                    util = pynvml.nvmlDeviceGetUtilizationRates(device['handle'])
                    mem_info = pynvml.nvmlDeviceGetMemoryInfo(device['handle'])
                    
                    device_data = {
                        'id': device['index'],
                        'name': device['name'],
                        'load': util.gpu,
                        'memory_used': mem_info.used // (1024 * 1024),
                        'memory_total': mem_info.total // (1024 * 1024)
                    }
                    
                    gpu_device_info.append(device_data)
                except pynvml.NVMLError as err:
                    logging.error(f"查询GPU信息时出错: {err}")
        
            self._last_gpu_update_time = time.time()
            self.update_gpu_device.emit(gpu_device_info)
            
            elapsed = self._timer.elapsed()
            self.performance_stats.emit({
                'gpu_count': len(gpu_device_info),
                'gpu_time': elapsed
            })
        except Exception as e:
            logging.error(f"刷新GPU设备信息时出错: {e}")
            self.update_gpu_device.emit([])

    def run(self):
        """工作线程主循环"""
        logging.info("工作线程开始运行")
        list_timer = 0
        monitor_timer = 0
        gpu_timer = 0
        gpu_device_timer = 0  # 新增GPU设备信息更新定时器
        
        try:
            while self._is_running:
                current_time = 100  # 每次循环约100ms
                
                if list_timer >= self._list_refresh_interval:
                    self.refresh_processes()
                    list_timer = 0
                
                if monitor_timer >= self._monitor_refresh_interval and self._monitored_pids:
                    self.refresh_monitored()
                    monitor_timer = 0
                
                if gpu_timer >= self._gpu_refresh_interval and self._monitored_pids:
                    self.refresh_gpu_info()
                    gpu_timer = 0
                
                if gpu_device_timer >= self._gpu_refresh_interval and GLOBAL_NVML_INITIALIZED:
                    self.refresh_gpu_device_info()
                    gpu_device_timer = 0
                
                QThread.msleep(current_time)
                list_timer += current_time
                monitor_timer += current_time
                gpu_timer += current_time
                gpu_device_timer += current_time
        except Exception as e:
            logging.critical(f"工作线程发生错误: {e}")
            self._is_running = False
            raise

    def _calculate_cpu_percent(self, pid):
        """计算CPU使用率"""
        try:
            proc = psutil.Process(pid)
            current_times = proc.cpu_times()
            
            if pid in self._last_cpu_times:
                last_times = self._last_cpu_times[pid]
                delta_proc = (current_times.user - last_times.user + 
                             current_times.system - last_times.system)
                delta_time = self._monitor_refresh_interval / 1000
                cpu_percent = (delta_proc / delta_time) * 100
            else:
                cpu_percent = proc.cpu_percent(interval=0)
                
            self._last_cpu_times[pid] = current_times
            return min(cpu_percent, 100)
        except (psutil.NoSuchProcess, psutil.AccessDenied) as err:
            logging.warning(f"计算进程 {pid} CPU 使用率时出错: {err}")
            return 0
        
    def set_refresh_intervals(self, list_interval, monitor_interval):
        """设置刷新间隔时间"""
        self._list_refresh_interval = list_interval
        self._monitor_refresh_interval = monitor_interval
        logging.info(f"设置刷新间隔: 列表={list_interval}ms, 监视={monitor_interval}ms")

    def set_monitored(self, pids):
        """设置要监视的进程"""
        if len(pids) > MAX_MONITOR_PROCESSES:
            pids = pids[:MAX_MONITOR_PROCESSES]
            logging.warning(f"监视进程数量超过限制，只监视前 {MAX_MONITOR_PROCESSES} 个进程")
        
        logging.info(f"设置监视进程: {pids}")
        self._last_selected_pids = set(pids)
        self._monitored_pids = list(pids)
        self._last_cpu_times = {}
        self._last_disk_io = {}
        self._last_net_io = {}
        self._last_gpu_info = {}  # 清空GPU缓存
        
        if len(pids) > 20:
            self._monitor_refresh_interval = max(200, self._monitor_refresh_interval)
        elif len(pids) > 50:
            self._monitor_refresh_interval = max(500, self._monitor_refresh_interval)
    
    def stop(self):
        """安全停止工作线程"""
        logging.info("停止工作线程")
        self._is_running = False
        
        # 关闭线程池
        if hasattr(self, '_executor') and self._executor is not None:
            try:
                self._executor.shutdown(wait=False)
                logging.info("线程池执行器已关闭")
            except Exception as e:
                logging.error(f"关闭线程池时出错: {e}")
            finally:
                self._executor = None

    def __del__(self):
        """析构函数确保资源释放"""
        if hasattr(self, '_executor') and self._executor is not None:
            try:
                self._executor.shutdown(wait=False)
                logging.info("线程池执行器已关闭")
            except Exception as e:
                logging.error(f"关闭线程池时出错: {e}")
        
        if GLOBAL_NVML_INITIALIZED:
            try:
                pynvml.nvmlShutdown()
                logging.info("NVML已关闭")
            except pynvml.NVMLError as err:
                logging.error(f"关闭NVML时出错: {err}")