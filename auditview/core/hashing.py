import hashlib


def line_hash(content):
    return hashlib.sha256(content.encode()).hexdigest()


def context_hash(prev, curr, nxt):
    combined = prev + "\n" + curr + "\n" + nxt
    return hashlib.sha256(combined.encode()).hexdigest()
