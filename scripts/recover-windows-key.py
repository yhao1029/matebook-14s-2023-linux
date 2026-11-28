"""Prepared for review: recover only the existing Goodix communication key.

No sensor access, network activity, Windows writes, SAM reads, biometric database
reads, or credential enumeration. Run only after explicit user authorization.
Uses Impacket 0.13.0 (Fortra, Apache-style license) for DPAPI/registry parsing.
"""
import argparse
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import resource
import sys
import uuid

resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
logging.disable(logging.CRITICAL)

from impacket import winregistry
from impacket.dpapi import DPAPI_BLOB, DPAPI_SYSTEM, MasterKey, MasterKeyFile
from impacket.examples.secretsdump import LSASecrets, LSA_SECRET, LSA_SECRET_BLOB

BASE = Path(__file__).resolve().parent
WINDOWS = None
CACHE = None
DEST = None
SOURCE = None


class ReadOnlyHive:
    """File wrapper for Impacket's file-object parser; never permits writes.

    Its isRemote switch selects the file-object API, not a network connection.
    Avoid the default path API, which opens local hives in r+b mode.
    """
    def __init__(self, path):
        self.fd = open(path, 'rb')

    def open(self):
        pass

    def read(self, *args):
        return self.fd.read(*args)

    def seek(self, *args):
        return self.fd.seek(*args)

    def close(self):
        self.fd.close()


def registry(path):
    return winregistry.saveRegistryParser(ReadOnlyHive(path), isRemote=True)


class OnlyDpapiSystem(LSASecrets):
    ALLOWED = frozenset(p.lower() for p in (
        r'\Policy\PolEKList\default',
        r'\Policy\PolSecretEncryptionKey\default',
        r'\Policy\Secrets\DPAPI_SYSTEM\CurrVal\default'))

    def __init__(self, parser, boot_key):
        super().__init__(None, boot_key, isRemote=False,
                         perSecretCallback=lambda *_: None)
        self._OfflineRegistry__registryHive = parser

    def getValue(self, path):
        if path.lower() not in self.ALLOWED:
            raise RuntimeError('Blocked registry value outside the approved scope')
        return super().getValue(path)

    def enumKey(self, *_):
        raise RuntimeError('Credential enumeration is disabled')

    enumValues = enumKey
    setValue = enumKey

    def recover(self):
        # Private APIs are pinned to Impacket 0.13.0; fail closed if incompatible.
        self._LSASecrets__getLSASecretKey()
        if not self._LSASecrets__vistaStyle or not self._LSASecrets__LSAKey:
            raise RuntimeError('Unsupported LSA protection format')
        value = self.getValue(r'\Policy\Secrets\DPAPI_SYSTEM\CurrVal\default')
        if value is None:
            raise RuntimeError('DPAPI_SYSTEM entry unavailable')
        encrypted = LSA_SECRET(value[1])['EncryptedData']
        key = self._LSASecrets__sha256(self._LSASecrets__LSAKey, encrypted[:32])
        plain = self._LSASecrets__cryptoCommon.decryptAES(key, encrypted[32:])
        return DPAPI_SYSTEM(LSA_SECRET_BLOB(plain)['Secret'])


def boot_key(parser):
    control = parser.getValue(r'\Select\Current')[1]
    parts = [parser.getClass(f'\\ControlSet{control:03d}\\Control\\Lsa\\{name}')
             [:16].decode('utf-16le') for name in ('JD', 'Skew1', 'GBG', 'Data')]
    scrambled = bytes.fromhex(''.join(parts))
    order = (8, 5, 4, 2, 11, 9, 13, 3, 0, 6, 1, 12, 14, 10, 15, 7)
    return bytes(scrambled[i] for i in order)


def entropy(seed):
    # Reuse the driver's documented derivation without executing its main().
    path = SOURCE
    spec = importlib.util.spec_from_file_location('goodix_cache_format', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.derive_entropy(seed)


def recover():
    if DEST.exists() or DEST.is_symlink():
        raise RuntimeError('Output already exists; refusing to overwrite')
    cache = CACHE.read_bytes()
    if not 56 <= len(cache) <= 4096:
        raise RuntimeError('Unexpected Goodix cache size')
    blob = DPAPI_BLOB(cache[:-8])
    if not blob['Flags'] & 4:
        raise RuntimeError('Cache is not protected in the expected machine scope')
    master_name = str(uuid.UUID(bytes_le=blob['GuidMasterKey']))
    system = registry(WINDOWS / 'System32/config/SYSTEM')
    security = registry(WINDOWS / 'System32/config/SECURITY')
    try:
        keys = OnlyDpapiSystem(security, boot_key(system)).recover()
        protect = WINDOWS / 'System32/Microsoft/Protect/S-1-5-18'
        psk = None
        for subdir, keyname in (('', 'MachineKey'), ('User', 'UserKey')):
            target = protect / subdir / master_name
            if not target.is_file():
                continue
            data = target.read_bytes()
            header = MasterKeyFile(data)
            master = MasterKey(data[len(header):len(header) + header['MasterKeyLen']])
            unsealed_master = master.decrypt(keys[keyname])
            if unsealed_master:
                candidate = blob.decrypt(unsealed_master, entropy(cache[-8:]))
                if candidate is not None and len(candidate) == 32:
                    psk = candidate
                    break
        if psk is None:
            raise RuntimeError('Goodix cache integrity/decryption check did not succeed')
        os.umask(0o077)
        DEST.parent.mkdir(mode=0o700, exist_ok=True)
        stat = DEST.parent.lstat()
        if DEST.parent.is_symlink() or stat.st_uid != os.getuid() or stat.st_mode & 0o077:
            raise RuntimeError('Output directory is not private to the current user')
        fd = os.open(DEST, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(psk)
        except BaseException:
            DEST.unlink(missing_ok=True)
            raise
        print(json.dumps({'status': 'recovered', 'key_bytes': 32, 'output_mode': '0600',
                          'sensor_accessed': False, 'windows_modified': False,
                          'fingerprint_templates_accessed': False}))
    finally:
        system.close()
        security.close()


def self_test():
    # Exercise scope guards with fabricated input; never open host hives/cache.
    reader = OnlyDpapiSystem.__new__(OnlyDpapiSystem)
    for forbidden in (r'\Policy\Secrets\OtherSecret\CurrVal\default',
                      r'\Policy\Secrets\DPAPI_SYSTEM\OldVal\default'):
        try:
            reader.getValue(forbidden)
        except RuntimeError:
            pass
        else:
            raise AssertionError('Read restriction failed')
    for operation in (reader.enumKey, reader.enumValues, reader.setValue):
        try:
            operation('unused')
        except RuntimeError:
            pass
        else:
            raise AssertionError('Enumeration/write restriction failed')
    assert len(entropy(bytes(8))) == 48
    print('Scope guards passed; no Windows files or real key material accessed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--self-test', action='store_true')
    modes.add_argument('--recover-existing-communication-key', action='store_true')
    parser.add_argument('--windows-root', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--format-helper', type=Path, required=True)
    args = parser.parse_args()
    global WINDOWS, CACHE, DEST, SOURCE
    SOURCE = args.format_helper.resolve()
    if not args.self_test:
        if not args.windows_root or not args.output:
            parser.error('--windows-root and --output required')
        root = args.windows_root.resolve()
        WINDOWS = root / 'Windows'
        CACHE = root / 'ProgramData/Goodix/Goodix_Cache.bin'
        DEST = args.output.resolve()
        import subprocess
        for path in (WINDOWS, CACHE):
            mount = subprocess.check_output(['findmnt', '-n', '-o', 'OPTIONS', '--target', str(path)], text=True)
            if 'ro' not in mount.strip().split(','):
                raise RuntimeError('Windows volume must already be mounted read-only')
        for relative in ('System32/config/SYSTEM', 'System32/config/SECURITY', 'System32/Microsoft/Protect/S-1-5-18'):
            resolved = (WINDOWS / relative).resolve()
            if not resolved.is_relative_to(root):
                raise RuntimeError('Windows source escapes selected volume')
    if args.self_test:
        self_test()
    else:
        recover()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Do not print exception payloads or tracebacks containing secret data.
        print('Operation stopped: ' + type(error).__name__ + '. No secret values displayed.', file=sys.stderr)
        sys.exit(1)
