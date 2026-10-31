"""App-owned model metadata and SilicoLab-only macOS Keychain secrets."""
import ctypes
import json
import os
from pathlib import Path
import socket
import threading
from urllib.parse import urlsplit
import uuid


class KeychainSecrets:
    """No shell, credential arguments, ambient auth, or other app namespaces."""
    SERVICE = 'com.silicolab.model-credentials'

    def _operate(self, operation, identity, value=None):
        if os.uname().sysname != 'Darwin':
            raise ValueError('模型凭据安全存储仅支持 macOS Keychain')
        from ctypes import c_void_p, c_long, c_int, c_char_p, POINTER, byref
        cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        sec = ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
        cf.CFStringCreateWithCString.argtypes = [c_void_p, c_char_p, ctypes.c_uint32]
        cf.CFStringCreateWithCString.restype = c_void_p
        cf.CFDataCreate.argtypes = [c_void_p, c_void_p, c_long]
        cf.CFDataCreate.restype = c_void_p
        cf.CFDictionaryCreate.argtypes = [c_void_p, POINTER(c_void_p), POINTER(c_void_p), c_long, c_void_p, c_void_p]
        cf.CFDictionaryCreate.restype = c_void_p
        cf.CFRelease.argtypes = [c_void_p]
        owned = []
        def constant(name):
            return c_void_p.in_dll(sec, name).value
        def string(text):
            pointer = cf.CFStringCreateWithCString(None, text.encode(), 0x08000100)
            owned.append(pointer)
            return pointer
        def dictionary(pairs):
            pointer = cf.CFDictionaryCreate(None, (c_void_p * len(pairs))(*[k for k, _ in pairs]), (c_void_p * len(pairs))(*[v for _, v in pairs]), len(pairs), None, None)
            owned.append(pointer)
            return pointer
        pairs = [(constant('kSecClass'), constant('kSecClassGenericPassword')),
                 (constant('kSecAttrService'), string(self.SERVICE)),
                 (constant('kSecAttrAccount'), string(identity))]
        try:
            if operation == 'get':
                pairs.append((constant('kSecReturnData'), c_void_p.in_dll(cf, 'kCFBooleanTrue').value))
                pairs.append((constant('kSecMatchLimit'), constant('kSecMatchLimitOne')))
                result = c_void_p()
                sec.SecItemCopyMatching.argtypes = [c_void_p, POINTER(c_void_p)]
                sec.SecItemCopyMatching.restype = c_int
                status = sec.SecItemCopyMatching(dictionary(pairs), byref(result))
                if status == -25300:
                    return None
                if status == 0:
                    owned.append(result.value)
                    cf.CFDataGetLength.argtypes = [c_void_p]
                    cf.CFDataGetLength.restype = c_long
                    cf.CFDataGetBytePtr.argtypes = [c_void_p]
                    cf.CFDataGetBytePtr.restype = c_void_p
                    return ctypes.string_at(cf.CFDataGetBytePtr(result), cf.CFDataGetLength(result)).decode()
            elif operation == 'delete':
                sec.SecItemDelete.argtypes = [c_void_p]
                sec.SecItemDelete.restype = c_int
                status = sec.SecItemDelete(dictionary(pairs))
                if status == -25300:
                    return None
            else:
                raw = value.encode()
                data = cf.CFDataCreate(None, ctypes.cast(c_char_p(raw), c_void_p), len(raw))
                owned.append(data)
                attributes = [(constant('kSecValueData'), data)]
                sec.SecItemUpdate.argtypes = [c_void_p, c_void_p]
                sec.SecItemUpdate.restype = c_int
                status = sec.SecItemUpdate(dictionary(pairs), dictionary(attributes))
                if status == -25300:
                    sec.SecItemAdd.argtypes = [c_void_p, POINTER(c_void_p)]
                    sec.SecItemAdd.restype = c_int
                    status = sec.SecItemAdd(dictionary(pairs + attributes), None)
            if status != 0:
                raise ValueError('SilicoLab Keychain 操作失败，请检查本机访问许可')
        finally:
            for pointer in reversed(owned):
                cf.CFRelease(pointer)

    def get(self, identity):
        return self._operate('get', identity)
    def set(self, identity, value):
        self._operate('set', identity, value)
    def delete(self, identity):
        self._operate('delete', identity)


class ModelCredentialChannel:
    """Anonymous per-host channel, never stored in a project or process environment."""
    def __init__(self, configuration):
        self.configuration = configuration
        self.client, self.server = socket.socketpair()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        try:
            with self.server.makefile('rb') as incoming:
                while True:
                    raw = incoming.readline(65537)
                    if not raw:
                        break
                    if len(raw) > 65536:
                        break
                    request = json.loads(raw)
                    try:
                        identity = str(uuid.UUID(request['configurationId']))
                        result = self.configuration.resolve(identity)
                        response = {'id': request['id'], 'result': result}
                    except Exception:
                        response = {'id': request.get('id'), 'error': '所选模型凭据不可用；未切换接收方，请检查设置'}
                    self.server.sendall((json.dumps(response) + '\n').encode())
        except (OSError, ValueError):
            pass
        finally:
            self.server.close()

    def detach_client(self):
        self.client.close()

    def close(self):
        self.client.close()
        try:
            self.server.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.thread.join(timeout=5)


class ModelConfiguration:
    def __init__(self, path, secrets=None):
        self.path = Path(path)
        self.secrets = secrets if secrets is not None else KeychainSecrets()
        self.lock = threading.RLock()

    def _read(self):
        if self.path.is_symlink():
            raise ValueError('模型配置不能是符号链接')
        try:
            values = json.loads(self.path.read_text())
            if not isinstance(values, list):
                raise ValueError()
            return values
        except FileNotFoundError:
            return []
        except (OSError, ValueError):
            raise ValueError('模型应用配置无法读取；原文件已保留') from None

    def _write(self, values):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError('模型配置不能是符号链接')
        temporary = self.path.with_name(f'model-configs-{uuid.uuid4().hex}.tmp')
        try:
            with open(temporary, 'x', opener=lambda p, f: os.open(p, f, 0o600)) as output:
                json.dump(values, output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def list(self):
        with self.lock:
            return [dict(item) for item in self._read()]

    def save(self, values):
        with self.lock:
            name, protocol, endpoint, model, key = (values.get(k) for k in ('name', 'protocol', 'baseUrl', 'modelId', 'apiKey'))
            if not all(isinstance(v, str) and v.strip() for v in (name, protocol, endpoint, model, key)):
                raise ValueError('请填写名称、明确协议、端点、模型 ID 和 API key')
            if protocol not in ('openai-responses', 'anthropic-messages') or len(name) > 100 or len(model) > 200 or len(endpoint) > 2000 or len(key) > 8192 or any(ord(c) < 32 for c in key):
                raise ValueError('模型配置格式或协议不支持')
            try:
                url = urlsplit(endpoint)
                if url.username or url.password or url.query or url.fragment or not url.hostname or url.scheme not in ('http', 'https'):
                    raise ValueError()
                if url.scheme == 'http' and url.hostname not in ('127.0.0.1', 'localhost', '::1'):
                    raise ValueError()
                url.port
            except ValueError:
                raise ValueError('端点须为 HTTPS（回环可 HTTP），不能包含认证、查询或片段') from None
            identity = str(uuid.uuid4())
            item = {'id': identity, 'name': name, 'protocol': protocol, 'baseUrl': endpoint.rstrip('/'),
                    'modelId': model, 'hasKey': True, 'verification': 'unverified'}
            self.secrets.set(identity, key)
            try:
                self._write(self._read() + [item])
            except Exception:
                self.secrets.delete(identity)
                raise
            return dict(item)

    def verify(self, identity):
        import shutil
        import subprocess
        configuration = self.resolve(identity)
        runtime = Path(os.environ.get('SILICOLAB_RUNTIME', Path(__file__).resolve().parents[3] / 'runtime'))
        node = os.environ.get('SILICOLAB_NODE') or shutil.which('node')
        if not node:
            raise ValueError('模型运行时未安装')
        try:
            result = subprocess.run([node, str(runtime / 'src/verify-model.ts')], input=json.dumps(configuration), text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=40,
                                    env={'PATH': '/usr/bin:/bin', 'LANG': 'en_US.UTF-8'}, close_fds=True)
            response = json.loads(result.stdout)
            if result.returncode or not response.get('ok'):
                raise ValueError()
        except (OSError, ValueError, subprocess.SubprocessError):
            raise ValueError('模型检查失败：凭据、网络或协议不兼容；未切换接收方') from None
        with self.lock:
            items = self._read()
            item = next((item for item in items if item['id'] == identity), None)
            if not item:
                raise ValueError('模型配置已移除')
            item['verification'] = 'verified_transport'
            from datetime import datetime, timezone
            item['verifiedAt'] = datetime.now(timezone.utc).isoformat()
            self._write(items)
            return dict(item)

    def resolve(self, identity):
        with self.lock:
            item = next((item for item in self._read() if item['id'] == identity), None)
            if not item:
                raise ValueError('所选模型未配置或已移除；未切换接收方')
            key = self.secrets.get(identity)
            if not key:
                raise ValueError('所选模型缺少 API key；请在设置中重新配置')
            return dict(item, apiKey=key)

    def delete(self, identity):
        with self.lock:
            items = self._read()
            self.secrets.delete(identity)
            self._write([item for item in items if item['id'] != identity])
            return {'removed': True}
