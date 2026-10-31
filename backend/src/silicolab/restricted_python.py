"""Issue #3 experiment: single-process Python under macOS Seatbelt.

Not a production executor or a portable sandbox. Never falls back to unsandboxed
execution. Only use artificial data and a trusted, preinstalled runtime.
"""
from __future__ import annotations

import errno
import hashlib
from importlib.metadata import distribution
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import signal
import stat
import subprocess
import sys
import sysconfig
import tempfile

PACKAGES = {"openpyxl": ("3.1.5", "openpyxl"), "et-xmlfile": ("2.0.0", "et_xmlfile")}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _limits():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


class PythonProbe:
    """Owner of temporary task copies and supervised analysis processes."""

    def __init__(self, runtime=None):
        if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
            raise RuntimeError("macOS sandbox-exec unavailable; execution blocked")
        self._executable = Path(sys.executable).resolve()
        self._stdlib = Path(sysconfig.get_path('stdlib')).resolve()
        self._runtime = Path(runtime).resolve() if runtime else None
        if self._runtime:
            self._executable = self._runtime / 'bin/python3.13'
            self._stdlib = self._runtime / 'lib/python3.13'
        self._temporary = tempfile.TemporaryDirectory(prefix="silicolab-python-probe-")
        self.directory = Path(self._temporary.name).resolve()
        self._runs: list[Analysis] = []
        self._closed = False
        self._packages = self.directory / "preinstalled"
        self._packages.mkdir()
        try:
            for name, (version, module) in PACKAGES.items():
                if self._runtime:
                    package = self._stdlib / 'site-packages' / module
                    metadata = list((self._stdlib / 'site-packages').glob(name.replace('-', '_') + '-*.dist-info/METADATA'))
                    if len(metadata) != 1 or f'Version: {version}\n' not in metadata[0].read_text():
                        raise RuntimeError(f'preinstall {name}=={version}; no automatic installation')
                else:
                    installed = distribution(name)
                    if installed.version != version:
                        raise RuntimeError(f"preinstall {name}=={version}; no automatic installation")
                    package = Path(installed.locate_file(module))
                if package.is_symlink() or any(path.is_symlink() for path in package.rglob("*")):
                    raise ValueError("preinstalled package contains a symlink; materialization blocked")
                shutil.copytree(package, self._packages / module,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        except BaseException:
            self._temporary.cleanup()
            raise
        runtime_build = platform.python_build()
        if self._runtime:
            metadata = subprocess.run([str(self._executable), '-I', '-S', '-B', '-c', 'import json,platform,sys; print(json.dumps([sys.version.split()[0],platform.python_build()]))'], env={'PATH':'/usr/bin:/bin'}, capture_output=True, text=True, timeout=5, check=True)
            version, runtime_build = json.loads(metadata.stdout)
            if version != '3.13.18': raise RuntimeError('Independent Python version mismatch; blocked')
        self.environment = {
            "python": "3.13.18" if self._runtime else sys.version.split()[0],
            "python_build": runtime_build,
            "executable_sha256": _digest(self._executable),
            "platform": sys.platform,
            "macos": platform.mac_ver()[0],
            "machine": platform.machine(),
            "packages": {name: version for name, (version, _) in PACKAGES.items()},
            "sandbox": "macOS Seatbelt via deprecated sandbox-exec; single-process policy",
        }

    def start(self, code: str, *, inputs=()) -> Analysis:
        if self._closed:
            raise RuntimeError("probe already closed")
        task = Path(tempfile.mkdtemp(prefix="task-", dir=self.directory))
        input_directory = task / "inputs"
        output_directory = task / "outputs"
        input_directory.mkdir()
        output_directory.mkdir()
        source_hashes = {}
        for source in inputs:
            source = Path(source).resolve(strict=True)
            if not source.is_file() or source.name in source_hashes:
                raise ValueError("inputs must be distinct files")
            shutil.copyfile(source, input_directory / source.name)
            source_hashes[source.name] = (source, _digest(source))
        script = task / "analysis.py"
        script.write_text(code, encoding="utf-8")
        executable = self._executable.resolve(strict=True)
        stdlib = self._stdlib.resolve(strict=True)
        read_paths = [f"(subpath {json.dumps(str(path), ensure_ascii=False)})" for path in
                      [stdlib, self._packages, input_directory, output_directory, Path("/System/Library"), Path("/usr/lib")]]
        # The root directory itself is needed by dyld; this is not a recursive grant.
        read_paths += [f"(literal {json.dumps(str(path), ensure_ascii=False)})" for path in
                       [Path("/"), executable, script, Path("/dev/null"), Path("/dev/urandom")]]
        ffi = (self._runtime or Path(sys.base_prefix)) / "lib" / "libffi.8.dylib"
        if ffi.exists():
            read_paths.append(f"(literal {json.dumps(str(ffi.resolve()), ensure_ascii=False)})")
        profile = "\n".join([
            "(version 1)", "(deny default)",
            f"(allow process-exec (literal {json.dumps(str(executable), ensure_ascii=False)}))",
            "(allow file-read* " + " ".join(read_paths) + ")",
            "(allow file-read-metadata)",
            '(allow sysctl-read (sysctl-name "kern.ostype" "kern.osrelease" "kern.osversion" "kern.version" "kern.hostname" "hw.machine"))',
            f"(deny file-read* (subpath {json.dumps(str(stdlib / 'site-packages'), ensure_ascii=False)}))",
            f"(allow file-write* (subpath {json.dumps(str(output_directory), ensure_ascii=False)}))",
            # No process-fork, network, Mach lookup, signal, file-link or shell grants.
        ])
        (task / "profile.sb").write_text(profile, encoding="utf-8")
        bootstrap = (
            "import sys; from pathlib import Path; import mimetypes; mimetypes.knownfiles=[]; mimetypes.init(); "
            f"sys.path.insert(0, {str(self._packages)!r}); "
            f"INPUTS=Path({str(input_directory)!r}); "
            f"exec(compile(Path({str(script)!r}).read_text(), 'analysis.py', 'exec'))"
        )
        stdout = (output_directory / "stdout.txt").open("w+b")
        stderr = (output_directory / "stderr.txt").open("w+b")
        try:
            process = subprocess.Popen(
                ["/usr/bin/sandbox-exec", "-p", profile, str(executable), "-I", "-S", "-B", "-u", "-c", bootstrap],
                cwd=output_directory,
                env={"PATH": "/usr/bin:/bin", "HOME": str(output_directory), "TMPDIR": str(output_directory),
                     "LANG": "en_US.UTF-8", "PYTHONNOUSERSITE": "1"},
                stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, close_fds=True,
                start_new_session=True, preexec_fn=_limits,
            )
        except BaseException:
            stdout.close()
            stderr.close()
            raise
        run = Analysis(process, task, source_hashes, self.environment, stdout, stderr)
        self._runs.append(run)
        return run

    def close(self):
        if self._closed:
            return
        for run in self._runs:
            run.stop()
            run._stdout.close()
            run._stderr.close()
        self._temporary.cleanup()
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class Analysis:
    """Public observation, wait, stop, and artifact interface of one analysis."""

    def __init__(self, process, task, source_hashes, environment, stdout, stderr):
        self._process = process
        self._task = task
        self._source_hashes = source_hashes
        self._environment = environment
        self._stdout = stdout
        self._stderr = stderr
        self._stopped = False

    @property
    def pid(self):
        return self._process.pid

    def status(self):
        returncode = self._process.poll()
        state = "running" if returncode is None else (
            "stopped" if self._stopped else "completed" if returncode == 0 else "failed")
        unchanged = all(source.is_file() and _digest(source) == digest and
                        _digest(self._task / "inputs" / name) == digest
                        for name, (source, digest) in self._source_hashes.items())
        return {
            "status": state, "returncode": returncode, "pid": self.pid, "task_id": self._task.name,
            # Read retained descriptors, never paths an untrusted script can replace with symlinks.
            "stdout": os.pread(self._stdout.fileno(), 1024 * 1024, 0).decode(errors="replace"),
            "stderr": os.pread(self._stderr.fileno(), 1024 * 1024, 0).decode(errors="replace"),
            "inputs_unchanged": unchanged, "environment": self._environment,
        }

    def wait(self, *, timeout=15):
        try:
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.stop()
            raise
        return self.status()

    def stop(self):
        if self._process.poll() is None:
            self._stopped = True
            # Single process is enforced by the kernel policy. Kill PID even if it changed its group.
            try:
                os.kill(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self._process.wait(timeout=5)
        return self.status()

    def log(self, name, max_bytes=1024 * 1024):
        """Inspect retained descriptors, not replaceable output path aliases."""
        if name not in ('stdout', 'stderr'): raise ValueError('Unknown analysis log')
        descriptor = self._stdout if name == 'stdout' else self._stderr
        info = os.fstat(descriptor.fileno())
        if info.st_size > max_bytes:
            raise ValueError('分析日志超过1MiB应用上限；未静默截断')
        content = os.pread(descriptor.fileno(), max_bytes + 1, 0)
        if len(content) > max_bytes or len(content) != info.st_size:
            raise ValueError('分析日志在读取期间改变或超限')
        return content

    def artifacts(self):
        """List top-level names only; callers still use artifact() for no-follow bounded reads."""
        return sorted(path.name for path in (self._task / 'outputs').iterdir())

    def artifact(self, name: str) -> bytes:
        # Never dereference script-controlled symlinks in the unsandboxed host.
        # Use the already-open output directory and O_NOFOLLOW for one regular file.
        if not name or Path(name).name != name or name in {".", ".."}:
            raise ValueError("artifact must name a top-level regular output file")
        directory_fd = os.open(self._task / "outputs", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
            except OSError as error:
                if error.errno == errno.ELOOP:
                    raise ValueError("artifact symlinks are not readable") from error
                raise
            with os.fdopen(fd, "rb") as artifact:
                info = os.fstat(artifact.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 8 * 1024 * 1024:
                    raise ValueError("artifact must be a bounded regular file")
                return artifact.read(8 * 1024 * 1024 + 1)
        finally:
            os.close(directory_fd)
