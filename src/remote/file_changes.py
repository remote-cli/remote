import time

from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread
from typing import Callable, List

from watchdog.events import FileSystemEvent, PatternMatchingEventHandler
from watchdog.observers import Observer


class SyncedWorkSpaceHandler(PatternMatchingEventHandler):
    """Set has_changes when changes are notified by watchdog."""

    def __init__(
        self, has_changes: Event, ignore_patterns: List[str] = None,
    ):
        super().__init__(ignore_patterns=ignore_patterns)
        self.has_changes = has_changes

    def on_any_event(self, event: FileSystemEvent) -> None:
        """Sync local workspace when file changes"""
        self.has_changes.set()


class ProcessEvents(Thread):
    """Executes a callback when a change is produced."""

    def __init__(self, has_changes: Event, callback: Callable[[], None], settle_time: float = 1):
        super().__init__()
        self.do_run = True
        self.settle_time = settle_time
        self.has_changes = has_changes
        self.callback = callback

    def run(self):
        while self.do_run:
            time.sleep(self.settle_time)
            if self.has_changes.is_set() and self.do_run:
                self.has_changes.clear()
                self.callback()

    def stop(self):
        self.do_run = False


@contextmanager
def execute_on_file_change(
    local_root: Path, callback: Callable[[], None], settle_time: float = 1, ignore_patterns: List[str] = None
) -> None:
    """Execute callback whenever files change."""
    has_changes = Event()
    # Set up a worker thread to process the changes after the changes are settled as per the settle time.
    worker = ProcessEvents(has_changes=has_changes, callback=callback, settle_time=settle_time)
    # Start observing the local workspace.
    observer = Observer()
    observer.schedule(
        SyncedWorkSpaceHandler(has_changes=has_changes, ignore_patterns=ignore_patterns), local_root, recursive=True
    )
    try:
        worker.start()
        observer.start()
        yield
    finally:
        observer.stop()
        worker.stop()
        observer.join()
        worker.join()
