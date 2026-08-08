#***************************************************************
#  This file is part of Paintomics v3
#
#  Paintomics is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License as
#  published by the Free Software Foundation, either version 3 of
#  the License, or (at your option) any later version.
#
#  Paintomics is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Paintomics.  If not, see <http://www.gnu.org/licenses/>.
#
#  More info http://bioinfo.cipf.es/paintomics
#  Technical contact paintomics4@gmail.com
#
# THIS FILE CONTAINS THE FOLLOWING COMPONENT DECLARATION
#  - JobStatus
#  - WorkerStatus
#  - Queue
#  - Worker
#  - WorkerThread
#  - Job
#  -
#**************************************************************

#TODO: TIMEOUT
#TODO: AUTO REMOVE JOBS

import logging
from threading import RLock as threading_lock, Thread
from collections import deque
from enum import Enum

class JobStatus(Enum):
    QUEUED  ='queued'
    FINISHED='finished'
    FAILED  ='failed'
    STARTED ='started'
    DEFERRED='deferred'
    NOT_QUEUED='not queued'

class WorkerStatus(Enum):
    WORKING ='working'
    IDLE    ='idle'
    STOPPED ='stopped'

class Queue:
    def __init__(self):
        logging.info("CREATING NEW INSTANCE FOR Queue...")
        self.lock = threading_lock()
        self.queue= deque([])
        self.jobs = {}
        self.workers = []

    def start_worker(self, n_workers=1):
        ids = []
        worker_id=""
        for i in range(0, n_workers):
            worker_id = "w" + self.get_random_id()
            self.workers.append(Worker(worker_id, self))
            ids.append(worker_id)
        return ids

    def stop_worker(self, worker_id=None):
        try:
            self.lock.acquire() #LOCK CACHE
            if worker_id == None:
                for worker in self.workers:
                    if worker.must_die != True:
                        worker_id = worker.id
                        break
                if worker_id == None:
                    logging.info("All workers will die...")

            for worker in self.workers:
                if worker.id == worker_id:
                    worker.must_die = True
                    break
        finally:
            self.lock.release() #UNLOCK CACHE
            self.notify_workers()

    def remove_worker(self, worker_id):
        try:
            self.lock.acquire() #LOCK CACHE
            i=0
            for worker in self.workers:
                if worker.id == worker_id and worker.must_die == True:
                    self.workers.pop(i)
                    break
                i+=1
        finally:
            self.lock.release() #UNLOCK CACHE
            self.notify_workers()

    def enqueue(self, fn, args, job_id="", timeout=600):
        try:
            self.lock.acquire() #LOCK CACHE
            job = Job(fn, args)

            if job_id=="":
                job_id = self.get_random_id()
                while job_id in self.jobs:
                    job_id = self.get_random_id()
            elif job_id in self.jobs:
                # Check if it has finished, then remove
                if self.jobs.get(job_id).status == JobStatus.FINISHED:
                    self.get_result(job_id)
                else:
                    raise RuntimeError("Job already at the queue (Job id : " + job_id + ")")

            job.set_id(job_id)
            job.set_timeout(timeout)

            self.jobs[job_id] = job
            self.queue.append(job)

            logging.info("NEW JOB "  + job_id + " ADDED TO QUEUE...")
        finally:
            self.lock.release() #UNLOCK CACHE
            self.notify_workers()

    def dequeue(self):
        try:
            self.lock.acquire() #LOCK CACHE
            if len(self.queue) > 0:
                return self.queue.popleft()
            return None
        finally:
            self.lock.release() #UNLOCK CACHE

    def notify_workers(self):
        for worker in self.workers:
            worker.notify()

    def check_status(self, job_id):
        job = self.jobs.get(job_id, None)
        if job:
            return job.status
        return JobStatus.NOT_QUEUED

    def fetch_job(self, job_id):
        return self.jobs.get(job_id, None)

    def get_result(self, job_id, remove=True):
        """Return a job's result, consuming it if it has finished.

        The lookup and the removal run under the queue lock. They used to be a
        bare check-then-act on a shared dict, so two callers arriving together
        could both find the job and both try to take it; the loser got the
        JobStatus enum back, which the status handler then called getResponse()
        on. Locking makes "who gets the result" a decision rather than a race,
        and exactly one caller wins.
        """
        try:
            self.lock.acquire() #LOCK CACHE
            job = self.jobs.get(job_id, None)
            if job:
                if remove and (job.status == JobStatus.FINISHED or job.status == JobStatus.FAILED):
                    logging.info("Removing job " + job_id)
                    self.jobs.pop(job_id, None)
                return job.result
            return JobStatus.NOT_QUEUED
        finally:
            self.lock.release() #UNLOCK CACHE

    def get_error_message(self, job_id):
        job = self.jobs.get(job_id, None)
        if job:
            return job.error_message
        return None

    def get_random_id(self):
        """
        This function returns a new random job id
        @returns jobID
        """
        #RANDOM GENERATION OF THE JOB ID
        #TODO: CHECK IF NOT EXISTING ID
        import string, random
        jobID = ''.join(random.sample(string.ascii_letters+string.octdigits*5,10))
        return jobID

class Worker():
    def __init__(self, _id, _queue):
        self.id = _id
        self.queue = _queue
        self.status = WorkerStatus.IDLE
        self.must_die = False
        self.job = None
        # Guards the claim sequence in notify(). See there for why.
        self.lock = threading_lock()

    def notify(self):
        """Take one job, if this worker is free. Safe to call concurrently.

        This used to check the status, dequeue, assign self.job and start a
        thread without holding anything. Queue.dequeue() takes the queue lock,
        but the sequence around it was not atomic and self.job is a single slot
        on a shared Worker -- and Queue.enqueue() calls notify_workers() after
        releasing its own lock, so two submissions arriving together produce
        two concurrent notify() calls on the same worker.

        Both then saw a non-WORKING status, both dequeued -- taking two
        different jobs -- and the second assignment to self.job discarded the
        first. Observed on the server by submitting two example jobs at once:
        one was taken off the deque and never executed, still reporting QUEUED
        three minutes later with no error, while the other was started twice
        and had two threads writing the same output directory ("Failed while
        compressing directory", then AttributeError: 'NoneType' object has no
        attribute 'result' as one thread's finally cleared self.job under the
        other).

        The status is claimed inside the lock and *before* the thread starts:
        setting it in run() left exactly the window a second notify() needed.
        self.job is checked too, so a worker holding a job cannot be handed
        another even if its status has not been updated yet.
        """
        self.lock.acquire()
        try:
            if self.status == WorkerStatus.WORKING or self.job is not None:
                return
            if self.must_die:
                mustRemove = True
            else:
                job = self.queue.dequeue()
                if job is None:
                    return
                self.job = job
                self.status = WorkerStatus.WORKING
                WorkerThread(self).start()
                return
        finally:
            self.lock.release()

        # remove_worker() calls back into notify_workers(), so it must not run
        # while this worker's lock is held.
        if mustRemove:
            self.queue.remove_worker(self.id)

    def run(self):
        # Taken once, under the lock, rather than read from self.job
        # throughout: notify() owns that slot, and reading it repeatedly is
        # what let one thread's finally clear it while another was still using
        # it ("AttributeError: 'NoneType' object has no attribute 'result'").
        self.lock.acquire()
        try:
            job = self.job
        finally:
            self.lock.release()

        if job is None:                      # nothing claimed; nothing to do
            return

        try:
            logging.info("Worker " + self.id + " starts working...")
            #Execute the function
            fn = job.fn
            args = job.args
            job.status = JobStatus.STARTED
            job.result = fn(*args)
            job.status = JobStatus.FINISHED
        except Exception as ex:
            job.status = JobStatus.FAILED
            job.error_message = str(ex)
        finally:
            logging.info("Worker " + self.id + " stops working...")
            # Released under the lock so it cannot cross a concurrent claim in
            # notify(); the follow-up notify() is called after releasing, so a
            # long dequeue never blocks another submission.
            self.lock.acquire()
            try:
                self.status = WorkerStatus.IDLE
                self.job = None
            finally:
                self.lock.release()
            self.notify()

class WorkerThread (Thread):
    def __init__(self, worker):
        Thread.__init__(self)
        self.worker = worker
    def run(self):
        self.worker.run()

class Job:
    def __init__(self, fn, args):
        self.fn = fn
        self.args = args
        self.id = None
        self.timeout = 600
        self.status = JobStatus.QUEUED
        self.result = None
        self.error_message=None

    def set_id(self, _id):
        self.id = _id
    def set_timeout(self, _timeout):
        self.timeout = _timeout

    def is_finished(self):
        return  self.status == JobStatus.FINISHED
    def is_failed(self):
        return self.status == JobStatus.FAILED
    def get_status(self):
        return self.status