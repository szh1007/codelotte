## Bug

The read-modify-write in `increment()` (lines 8-10) is unsynchronized:

```python
    value = counter
    value += 1
    counter = value
```

Eight threads run this at the same time, so several can read the same `counter`
value before any of them stores its result.

## Why

Two threads, `counter == 0`:

1. T1 executes `value = counter` → T1's `value` is 0.
2. The GIL preempts T1 (switch interval elapsed) before `counter = value`.
3. T2 executes all three lines: reads 0, computes 1, stores `counter = 1`.
4. T1 resumes and stores `counter = 1`.

Two increments produced one update — a lost update. With 8 threads, `run(8)` can
return anything from 1 to 8.

The GIL does **not** make this atomic. The GIL only serializes bytecode
execution; it does not prevent a thread switch between `LOAD_GLOBAL counter` and
`STORE_GLOBAL counter`. Read-modify-write is three separate bytecode operations,
and a switch between them breaks the sequence. (On some CPython builds a single
`counter += 1` happens to be compiled into few enough bytecodes to appear safe,
but that is an implementation detail of one version and is not a language
guarantee.)

## Fix

Guard the whole read-modify-write with a `threading.Lock`:

```python
import threading

counter = 0
counter_lock = threading.Lock()   # one lock, module level, next to counter


def increment():
    global counter
    with counter_lock:
        counter += 1
```

Where the lock lives: at **module level, beside `counter`** — it is a single
shared object created once at import. Creating it inside `increment()` (or
anywhere per-call/per-thread) would give each thread its own lock and provide
no mutual exclusion. Both `increment()` and any other writer must use the same
`counter_lock`, and any read that is not already ordered by `worker.join()`
should take the lock too.
