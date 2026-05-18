import os


def pytest_addoption(parser):
    g = parser.getgroup("fuzz")
    g.addoption(
        "--fuzz-iters",
        type=int,
        default=100,
        help="Number of fuzz iterations to run (default: 100).",
    )
    g.addoption(
        "--fuzz-seed",
        type=int,
        default=0,
        help="Base seed; iteration i uses seed (base + i) (default: 0).",
    )
    g.addoption(
        "--fuzz-save-fn",
        action="store_true",
        default=False,
        help="Also save a capped sample of false-unmark outcomes to saved_seeds/.",
    )
    g.addoption(
        "--fuzz-jobs",
        type=int,
        default=os.cpu_count() or 4,
        help="Number of parallel worker processes (default: cpu_count).",
    )
