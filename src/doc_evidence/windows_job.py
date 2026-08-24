"""Small Windows Job Object adapter for kill-on-close process trees."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Any, Self, cast

from doc_evidence.errors import RequestError

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_SYNCHRONIZE = 0x00100000
_WAIT_TIMEOUT = 0x00000102
_windows_ctypes = cast(Any, ctypes)


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("per_process_user_time_limit", ctypes.c_int64),
        ("per_job_user_time_limit", ctypes.c_int64),
        ("limit_flags", wintypes.DWORD),
        ("minimum_working_set_size", ctypes.c_size_t),
        ("maximum_working_set_size", ctypes.c_size_t),
        ("active_process_limit", wintypes.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority_class", wintypes.DWORD),
        ("scheduling_class", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("read_operation_count", ctypes.c_uint64),
        ("write_operation_count", ctypes.c_uint64),
        ("other_operation_count", ctypes.c_uint64),
        ("read_transfer_count", ctypes.c_uint64),
        ("write_transfer_count", ctypes.c_uint64),
        ("other_transfer_count", ctypes.c_uint64),
    ]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("basic_limit_information", _JobObjectBasicLimitInformation),
        ("io_info", _IoCounters),
        ("process_memory_limit", ctypes.c_size_t),
        ("job_memory_limit", ctypes.c_size_t),
        ("peak_process_memory_used", ctypes.c_size_t),
        ("peak_job_memory_used", ctypes.c_size_t),
    ]


def _windows_error() -> OSError:
    return _windows_ctypes.WinError(_windows_ctypes.get_last_error())


def _kernel32():
    if os.name != "nt":
        raise RequestError("Windows Job Objects are unavailable on this platform")
    return _windows_ctypes.WinDLL("kernel32", use_last_error=True)


def process_is_alive(process_id: int) -> bool:
    if process_id <= 0:
        return False
    kernel32 = _kernel32()
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    process = open_process(_SYNCHRONIZE, False, process_id)
    if not process:
        return False
    try:
        wait = kernel32.WaitForSingleObject
        wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        wait.restype = wintypes.DWORD
        return wait(process, 0) == _WAIT_TIMEOUT
    finally:
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        close_handle(process)


class WindowsJob:
    """Own a process tree whose members die when the final handle closes."""

    def __init__(self, handle: int):
        self._handle = handle

    @classmethod
    def create(cls) -> WindowsJob:
        kernel32 = _kernel32()
        create_job = kernel32.CreateJobObjectW
        create_job.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        create_job.restype = wintypes.HANDLE
        handle = create_job(None, None)
        if not handle:
            raise _windows_error()
        job = cls(int(handle))
        try:
            information = _JobObjectExtendedLimitInformation()
            information.basic_limit_information.limit_flags = (
                _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            set_information = kernel32.SetInformationJobObject
            set_information.argtypes = [
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.DWORD,
            ]
            set_information.restype = wintypes.BOOL
            if not set_information(
                wintypes.HANDLE(job._handle),
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                ctypes.byref(information),
                ctypes.sizeof(information),
            ):
                raise _windows_error()
        except BaseException:
            job.close()
            raise
        return job

    def assign(self, process_id: int) -> None:
        if not self._handle:
            raise RequestError("Windows Job Object is already closed")
        kernel32 = _kernel32()
        open_process = kernel32.OpenProcess
        open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        open_process.restype = wintypes.HANDLE
        process = open_process(
            _PROCESS_TERMINATE | _PROCESS_SET_QUOTA,
            False,
            process_id,
        )
        if not process:
            raise _windows_error()
        try:
            assign_process = kernel32.AssignProcessToJobObject
            assign_process.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            assign_process.restype = wintypes.BOOL
            if not assign_process(
                wintypes.HANDLE(self._handle),
                process,
            ):
                raise _windows_error()
        finally:
            self._close_handle(int(process))

    def terminate(self, exit_code: int = 1) -> None:
        if not self._handle:
            return
        kernel32 = _kernel32()
        terminate_job = kernel32.TerminateJobObject
        terminate_job.argtypes = [wintypes.HANDLE, wintypes.UINT]
        terminate_job.restype = wintypes.BOOL
        if not terminate_job(wintypes.HANDLE(self._handle), exit_code):
            raise _windows_error()

    @staticmethod
    def _close_handle(handle: int) -> None:
        kernel32 = _kernel32()
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        if not close_handle(wintypes.HANDLE(handle)):
            raise _windows_error()

    def close(self) -> None:
        handle = self._handle
        self._handle = 0
        if handle:
            self._close_handle(handle)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except OSError:
            return
