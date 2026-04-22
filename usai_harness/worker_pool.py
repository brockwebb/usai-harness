"""Worker Pool: Async workers pulling tasks from a queue.

Responsibilities:
    - N async workers (configurable, default 3)
    - Each worker: pull task from queue, acquire rate limiter token, fire request
    - Return results via callback or collected list
    - Graceful shutdown: drain queue, wait for in-flight requests

Inputs:
    - n_workers: int — number of concurrent workers (default: 3)
    - rate_limiter: RateLimiter instance
    - request_fn: async callable — the actual HTTP request function

Outputs:
    - submit(task) — add a task to the queue
    - run_batch(tasks) — process all tasks, return results
    - shutdown() — graceful stop
"""
