from multiprocessing import Process, Event, Manager, JoinableQueue
import src.config as c
import src.utils as u
import src.jobs_handler as job
import time
import sys
import time
import logging
import signal
import os
import pandas as pd
from src.jobs_handler import *
import src.plot as plot

pd.set_option('display.max_columns', 500)
pd.set_option('display.width', 1000)

TRACE = 5
DEBUG = logging.DEBUG
INFO = logging.INFO

main_pid = ""

import os
import sys

def sigterm_handler(signum, frame):
    """Handles the SIGTERM signal by performing cleanup actions and gracefully terminating all processes."""
    # Perform cleanup actions here
    # ...    
    global main_pid
    if os.getpid() == main_pid:
        print("SIGINT received. Performing cleanup...")
        for t in nodes_thread:
            t.terminate()
            t.join()    
            
        # ...
        print("All processes have been gracefully teminated.")
        sys.exit(0)  # Exit gracefully


import os
import signal
import logging

def setup_environment():
    """
    Set up the environment for the program.

    Registers the SIGTERM signal handler, sets the main process ID, and initializes logging.
    """
    signal.signal(signal.SIGINT, sigterm_handler)
    global main_pid
    main_pid = os.getpid()

    logging.addLevelName(TRACE, "TRACE")
    logging.basicConfig(filename='debug.log', level=INFO, format='%(message)s', filemode='w')

    logging.debug('Clients number: ' + str(c.num_clients))
    logging.debug('Edges number: ' + str(c.num_edges))
    logging.debug('Requests number: ' + str(c.req_number))
    
    
def setup_nodes(nodes_thread, terminate_processing_events, start_events, use_queue, manager, return_val, queues, progress_bid_events):
    """
    Sets up the nodes for processing. Generates threads for each node and starts them.
    
    Args:
    nodes_thread (list): A list of threads for each node.
    terminate_processing_events (list): A list of events to terminate processing for each node.
    start_events (list): A list of events to start processing for each node.
    use_queue (list): A list of events to indicate if a queue is being used by a node.
    manager (multiprocessing.Manager): A multiprocessing manager object.
    return_val (list): A list of return values for each node.
    queues (list): A list of queues for each node.
    progress_bid_events (list): A list of events to indicate progress of bid processing for each node.
    """
    for i in range(c.num_edges):
        q = JoinableQueue()
        e = Event() 
        
        queues.append(q)
        use_queue.append(e)
        
        e.set()

    #Generate threads for each node
    for i in range(c.num_edges):
        e = Event() 
        e2 = Event()
        e3 = Event()
        return_dict = manager.dict()
        
        c.nodes[i].set_queues(queues, use_queue)
        
        p = Process(target=c.nodes[i].work, args=(e, e2, e3, return_dict))
        nodes_thread.append(p)
        return_val.append(return_dict)
        terminate_processing_events.append(e)
        start_events.append(e2)
        e3.clear()
        progress_bid_events.append(e3)
        
        p.start()
        
    for e in start_events:
        e.wait()
        
    # print("All the processes started.")

def print_final_results(start_time):    
    logging.info('Tot messages: '+str(c.counter))
    # print('Tot messages: '+str(c.counter))
    logging.info("Run time: %s" % (time.time() - start_time))
    # print("Run time: %s" % (time.time() - start_time))

def collect_node_results(return_val, jobs, exec_time, time_instant):
    """
    Collects the results from the nodes and updates the corresponding data structures.
    
    Args:
    - return_val: list of dictionaries containing the results from each node
    - jobs: list of job objects
    - exec_time: float representing the execution time of the jobs
    - time_instant: int representing the current time instant
    
    Returns:
    - float representing the utility value calculated based on the updated data structures
    """
    c.counter = 0
    c.job_count = {}
    
    if time_instant != 0:
        for v in return_val: 
            c.nodes[v["id"]].bids = v["bids"]
            for key in v["counter"]:
                if key not in c.job_count:
                    c.job_count[key] = 0
                c.job_count[key] += v["counter"][key]
                c.counter += v["counter"][key]
            c.nodes[v["id"]].updated_cpu = v["updated_cpu"]
            c.nodes[v["id"]].updated_gpu = v["updated_gpu"]
            c.nodes[v["id"]].updated_bw = v["updated_bw"]
            c.nodes[v["id"]].gpu_type = v["gpu_type"]

        for j in job_ids:
            for i in range(c.num_edges):
                if j not in c.nodes[i].bids:
                    print('???????')
                    print(c.nodes[i].bids)
                    print(str(c.nodes[i].id) + ' ' +str(j))
                logging.info(
                    str(c.nodes[i].bids[j]['auction_id']) + 
                    ' id: ' + str(c.nodes[i].id) + 
                    ' complete: ' + str(c.nodes[i].bids[j]['complete']) +
                    ' complete_tiemstamp' + str(c.nodes[i].bids[j]['complete_timestamp'])+
                    ' count' + str(c.nodes[i].bids[j]['count'])+
                    ' used_tot_gpu: ' + str(c.nodes[i].initial_gpu)+' - ' +str(c.nodes[i].updated_gpu)  + ' = ' +str(c.nodes[i].initial_gpu - c.nodes[i].updated_gpu) + 
                    ' used_tot_cpu: ' + str(c.nodes[i].initial_cpu)+' - ' +str(c.nodes[i].updated_cpu)  + ' = ' +str(c.nodes[i].initial_cpu - c.nodes[i].updated_cpu) + 
                    ' used_tot_bw: '  + str(c.nodes[i].initial_bw)+' - '  +str(c.nodes[i].updated_bw) + ' = '  +str(c.nodes[i].initial_bw  - c.nodes[i].updated_bw))

    return u.calculate_utility(c.nodes, c.num_edges, c.counter, exec_time, c.req_number, jobs, c.a, time_instant)

def terminate_node_processing(nodes_thread, events):
    for e in events:
        e.set()
        
    # Block until all tasks are done.
    for nt in nodes_thread:
        nt.join()
        
def clear_screen():
    # Function to clear the terminal screen
    os.system('cls' if os.name == 'nt' else 'clear')

def print_simulation_values(time_instant, processed_jobs, queued_jobs, running_jobs):
    print("Infrastructure info")
    print(f"Number of nodes: {c.num_edges}")
    
    for t in set(c.gpu_types):
        count = 0
        for i in c.gpu_types:
            if i == t:
                count += 1
        print(f"Number of {t.name} GPU nodes: {count}")
    
    print()
    print("Performing simulation at time " + str(time_instant) + ".")
    print(f"# Jobs processed: \t\t{processed_jobs}/{len(c.dataset)}")
    print(f"# Jobs currently in queue: \t{queued_jobs}")
    print(f"# Jobs currently running: \t{running_jobs}")
        
def print_simulation_progress(time_instant, job_processed, queued_jobs, running_jobs):
    clear_screen()
    print_simulation_values(time_instant, job_processed, queued_jobs, running_jobs)

if __name__ == "__main__":
    
    # Set up the environment
    setup_environment()

    # Set up nodes and related variables
    nodes_thread = []
    terminate_processing_events = []
    start_events = []
    progress_bid_events = []
    use_queue = []
    manager = Manager()
    return_val = []
    queues = []
    setup_nodes(nodes_thread, terminate_processing_events, start_events, use_queue, manager, return_val, queues, progress_bid_events)

    # Get the simulation end time instant
    simulation_end = job.get_simulation_end_time_instant(c.dataset)

    # Initialize job-related variables
    job_ids=[]
    jobs = pd.DataFrame()
    running_jobs = pd.DataFrame()
    processed_jobs = pd.DataFrame()

    # Collect node results
    start_time = time.time()
    collect_node_results(return_val, pd.DataFrame(), time.time()-start_time, 0)
    
    # Start the simulation loop
    time_instant = 1
    while True:
        start_time = time.time()
        
        if time_instant%10 == 0:
            plot.plot_all(c.num_edges, c.filename, c.job_count, "plot")
        
        # Select jobs for the current time instant
        new_jobs = job.select_jobs(c.dataset, time_instant)
        
        # Add new jobs to the job queue
        jobs = pd.concat([jobs, new_jobs], sort=False)
        
        # Schedule jobs
        jobs = job.schedule_jobs(jobs)
        jobs_to_submit = job.create_job_batch(jobs, 10)
        
        # Dispatch jobs
        if len(jobs_to_submit) > 0:                   
            job.dispatch_job(jobs_to_submit, queues)

            for e in progress_bid_events:
                e.wait()
                e.clear() 
        
        # Collect node results
        exec_time = time.time() - start_time
        assigned_jobs, unassigned_jobs = collect_node_results(return_val, jobs_to_submit, exec_time, time_instant)
                   
        # Assign start time to assigned jobs
        assigned_jobs = job.assign_job_start_time(assigned_jobs, time_instant)
        
        # Add unassigned jobs to the job queue
        jobs = pd.concat([jobs, unassigned_jobs], sort=False)  
        running_jobs = pd.concat([running_jobs, assigned_jobs], sort=False)
        processed_jobs = pd.concat([processed_jobs,assigned_jobs], sort=False)
        
        # Extract completed jobs
        jobs_to_unallocate, running_jobs = job.extract_completed_jobs(running_jobs, time_instant)
        
        # Deallocate completed jobs
        if len(jobs_to_unallocate) > 0:
            for _, j in jobs_to_unallocate.iterrows():
                data = message_data(
                        j['job_id'],
                        j['user'],
                        j['num_gpu'],
                        j['num_cpu'],
                        j['duration'],
                        j['bw'],
                        j['gpu_type'],
                        deallocate=True
                    )
                for q in queues:
                    q.put(data)

            for e in progress_bid_events:
                e.wait()
                e.clear()

        # Deallocate unassigned jobs
        if len(unassigned_jobs) > 0:
            for _, j in unassigned_jobs.iterrows():
                data = message_data(
                        j['job_id'],
                        j['user'],
                        j['num_gpu'],
                        j['num_cpu'],
                        j['duration'],
                        j['bw'],
                        j['gpu_type'],
                        deallocate=True
                    )
                
                for q in queues:
                    q.put(data)
            
            for e in progress_bid_events:
                e.wait()
                e.clear()
            
        print_simulation_progress(time_instant, len(processed_jobs), len(jobs) + len(unassigned_jobs), len(running_jobs))
        time_instant += 1

        # Check if all jobs have been processed
        if len(processed_jobs) == len(c.dataset):# and len(running_jobs) == 0 and len(jobs) == 0: # add to include also the final deallocation
            break
    
    # Collect final node results
    collect_node_results(return_val, pd.DataFrame(), time.time()-start_time, time_instant)

    # Terminate node processing
    terminate_node_processing(nodes_thread, terminate_processing_events)

    # Save processed jobs to CSV
    processed_jobs.to_csv("jobs_report.csv")

    # Plot results
    if c.use_net_topology:
        c.network_t.dump_to_file(c.filename, c.a)

    print_final_results(start_time)

    plot.plot_all(c.num_edges, c.filename, c.job_count, "plot")
