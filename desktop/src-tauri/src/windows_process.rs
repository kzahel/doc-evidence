use std::{mem::size_of, os::windows::io::AsRawHandle, process::Child, ptr};
#[cfg(test)]
use windows_sys::Win32::System::JobObjects::{
    JobObjectBasicAccountingInformation, QueryInformationJobObject,
    JOBOBJECT_BASIC_ACCOUNTING_INFORMATION,
};
use windows_sys::Win32::{
    Foundation::{CloseHandle, HANDLE},
    System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, TerminateJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    },
};

pub(crate) struct KillOnCloseJob {
    handle: HANDLE,
}

// The owned kernel handle can be closed or used from any process thread.
unsafe impl Send for KillOnCloseJob {}

impl KillOnCloseJob {
    pub(crate) fn create() -> Result<Self, String> {
        let handle = unsafe { CreateJobObjectW(ptr::null(), ptr::null()) };
        if handle.is_null() {
            return Err("could not create the Windows sidecar job".to_string());
        }
        let mut information = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        information.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let configured = unsafe {
            SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                std::ptr::addr_of!(information).cast(),
                size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            )
        };
        if configured == 0 {
            unsafe {
                CloseHandle(handle);
            }
            return Err("could not configure the Windows sidecar job".to_string());
        }
        Ok(Self { handle })
    }

    pub(crate) fn assign(&self, child: &Child) -> Result<(), String> {
        let process = child.as_raw_handle() as HANDLE;
        if unsafe { AssignProcessToJobObject(self.handle, process) } == 0 {
            return Err("could not assign the sidecar launcher to its Windows job".to_string());
        }
        Ok(())
    }

    pub(crate) fn terminate(&self) {
        unsafe {
            TerminateJobObject(self.handle, 1);
        }
    }

    #[cfg(test)]
    fn active_processes(&self) -> Result<u32, String> {
        let mut information = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION::default();
        let queried = unsafe {
            QueryInformationJobObject(
                self.handle,
                JobObjectBasicAccountingInformation,
                std::ptr::addr_of_mut!(information).cast(),
                size_of::<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() as u32,
                ptr::null_mut(),
            )
        };
        if queried == 0 {
            return Err("could not inspect the Windows sidecar job".to_string());
        }
        Ok(information.ActiveProcesses)
    }
}

impl Drop for KillOnCloseJob {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.handle);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        io::Write,
        process::{Command, Stdio},
        thread,
        time::Duration,
    };

    #[test]
    fn job_owns_and_terminates_a_descendant_tree() {
        let job = KillOnCloseJob::create().unwrap();
        let mut root = Command::new("powershell.exe")
            .args([
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$null = [Console]::In.Read(); Start-Process ping.exe -ArgumentList @('-n','30','127.0.0.1'); Start-Sleep -Seconds 30",
            ])
            .stdin(Stdio::piped())
            .spawn()
            .unwrap();
        job.assign(&root).unwrap();
        root.stdin.take().unwrap().write_all(b"G").unwrap();
        let deadline = std::time::Instant::now() + Duration::from_secs(3);
        while job.active_processes().unwrap() < 2 && std::time::Instant::now() < deadline {
            thread::sleep(Duration::from_millis(20));
        }
        assert!(job.active_processes().unwrap() >= 2);

        job.terminate();
        root.wait().unwrap();
        let deadline = std::time::Instant::now() + Duration::from_secs(3);
        while job.active_processes().unwrap() != 0 && std::time::Instant::now() < deadline {
            thread::sleep(Duration::from_millis(20));
        }
        assert_eq!(job.active_processes().unwrap(), 0);
    }
}
