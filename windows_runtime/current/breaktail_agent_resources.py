"""Read-only host observations. No shell, process control or model calls."""
import ctypes
from datetime import datetime,timezone
import os
import shutil


def _windows_memory():
    if os.name!='nt':raise NotImplementedError('Windows memory provider only')
    class MemoryStatus(ctypes.Structure):
        _fields_=[('length',ctypes.c_uint32),('load',ctypes.c_uint32)]+[
            (name,ctypes.c_uint64) for name in ('total','available','page_total','page_available',
                                              'virtual_total','virtual_available','extended_available')]
    status=MemoryStatus()
    status.length=ctypes.sizeof(status)
    api=ctypes.WinDLL('kernel32',use_last_error=True).GlobalMemoryStatusEx
    api.argtypes=[ctypes.POINTER(MemoryStatus)]
    api.restype=ctypes.c_int
    if not api(ctypes.byref(status)):raise ctypes.WinError(ctypes.get_last_error())
    if not 0<status.total or not 0<=status.available<=status.total or not 0<=status.load<=100:
        raise ValueError('invalid OS memory counters')
    return {'total_bytes':status.total,'available_bytes':status.available,'load_percent':status.load}


def _observe(source,provider):
    try:
        return {'status':'observed','source':source,'values':provider()}
    except (OSError,ValueError,NotImplementedError) as error:
        return {'status':'unsupported' if isinstance(error,NotImplementedError) else 'unavailable',
                'source':source,'values':None,'error':type(error).__name__}


def observe(workspace):
    def cpu():
        count=os.cpu_count()
        if type(count) is not int or count<=0:raise ValueError('logical CPU count unavailable')
        return {'logical_processors':count}
    def disk():
        usage=shutil.disk_usage(workspace.root)
        if not 0<usage.total or not 0<=usage.free<=usage.total:raise ValueError('invalid disk counters')
        return {'total_bytes':usage.total,'used_bytes':usage.used,'free_bytes':usage.free}
    return {'schema':1,'observed_at_utc':datetime.now(timezone.utc).isoformat(),'read_only':True,
            'workspace':str(workspace.root),
            'cpu':_observe('os.cpu_count',cpu),
            'memory':_observe('Windows GlobalMemoryStatusEx',_windows_memory),
            'disk':_observe('shutil.disk_usage(workspace)',disk),
            'gpu':{'status':'not_connected','source':None,'values':None}}
