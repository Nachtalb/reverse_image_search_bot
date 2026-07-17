"""Abuse-report subsystem: encrypted NCMEC report pipeline.

Public surface:
- crypto: P1/P2 secrets, AES-GCM file encryption, page-secret hashing
- server: the aiohttp report webview (initData auth, blobs, NCMEC lifecycle)
- ncmec: submit/upload/file_info/finish/retract wrapper
"""
