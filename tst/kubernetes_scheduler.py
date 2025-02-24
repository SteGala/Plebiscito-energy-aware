import copy
import os
from tst.node import Node
from src.jobs_handler import message_data

import pandas as pd

num_layers = None
allocation = None
best_allocation = None
best_power_consumption = None

def is_valid_allocation(allocation, job, n_nodes):
    min_ = job["N_layer_min"]
    max_ = job["N_layer_max"]
    counter = [0 for i in range(n_nodes)]
    
    for id in allocation:
        counter[id] += 1
        
    for c in allocation:
        if counter[c] < min_ or counter[c] > max_:
            return False

    return True

class KubernetesScheduler:
    def __init__(self, nodes, dataset, filename, application_graph_type, split):
        self.dataset = dataset.sort_values(by=["submit_time"])
        self.compute_nodes = []
        self.filename = filename
        self.application_type = application_graph_type
        self.split = split
        
        for n in nodes:
            self.compute_nodes.append(Node(n.initial_cpu, n.initial_gpu, n.initial_bw, n.performance))
            
        print("KubernetesScheduler initialized")
            
    def save_node_state(self):
        d = {}
        
        for i, n in enumerate(self.compute_nodes):
            d["node_" + str(i) + "_cpu"] = n.used_cpu
            d["node_" + str(i) + "_gpu"] = n.used_gpu
            d["node_" + str(i) + "_bw"] = n.used_bw
            d['node_' + str(i) + '_cpu_consumption'] = n.performance.compute_current_power_consumption_cpu(n.used_cpu)
            d['node_' + str(i) + '_gpu_consumption'] = n.performance.compute_current_power_consumption_gpu(n.used_gpu)
            
        # append dictionary to exixting csv file
        df = pd.DataFrame(d, index=[0])
        
        if os.path.exists(self.filename + ".csv"):
            df.to_csv(self.filename + ".csv", mode='a', header=False, index=False)
        else:
            df.to_csv(self.filename + ".csv", mode='a', header=True, index=False)
            
    def run(self):
        time_instant = 1
        running_jobs = []
        
        print("KubernetesScheduler started")
        
        self.save_node_state()
        
        while len(self.dataset) > 0:
            
            self.deallocate(time_instant, running_jobs)
                
            jobs = self.dataset[self.dataset['submit_time'] <= time_instant]
            self.dataset.drop(self.dataset[self.dataset['submit_time'] <= time_instant].index, inplace = True)
            
            for _, job in jobs.iterrows():
                self.allocate(job, running_jobs, time_instant)
                
            self.save_node_state()
            time_instant += 1
            
        while len(running_jobs) > 0:
            self.deallocate(time_instant, running_jobs)
            self.save_node_state()
            time_instant += 1
        
        self.save_node_state()

    def deallocate(self, time_instant, running_jobs):
        end = False
        
        while not end:
            end = True
            for id, j in enumerate(running_jobs):
                if j["duration"] + j["exec_time"] < time_instant:
                    for i in range(len(j["cpu_per_node"])):
                        self.compute_nodes[i].deallocate(j["cpu_per_node"][i], j["gpu_per_node"][i], 0)
                    print(f"Deallocated job {j['job_id']}")
                    del running_jobs[id]
                    end = False
                    break

    def allocate(self, job, running_jobs, time_instant):                
        data = message_data(
                    job['job_id'],
                    job['user'],
                    job['num_gpu'],
                    job['num_cpu'],
                    job['duration'],
                    job['bw'],
                    job['gpu_type'],
                    deallocate=False,
                    split=self.split,
                    app_type=self.application_type
                )
        
        global best_allocation
        best_allocation = [-1 for i in range(data['N_layer'])]
                
        self.compute_allocation(data)
        
        if -1 in best_allocation:
            self.dataset = pd.concat([self.dataset, pd.DataFrame([job])], sort=False)
            #print(f"Failed to allocate job {job['job_id']}")
            return
        
        print(f"Allocated job {job['job_id']}")
        #print(best_allocation)
        cpu_per_node, gpu_per_node = self.compute_requirement_per_node(best_allocation, data)
        for i in range(len(cpu_per_node)):
            self.compute_nodes[i].allocate(cpu_per_node[i], gpu_per_node[i], 0)
            
        j = {}
        j['job_id'] = job['job_id']
        j['submit_time'] = job['submit_time']
        j['duration'] = job['duration']
        j['cpu_per_node'] = cpu_per_node
        j['gpu_per_node'] = gpu_per_node
        j['exec_time'] =  time_instant
        running_jobs.append(j)
               
    def compute_power_consumption(self, allocation, job):
        power_consumption = 0
        cpu_per_node, gpu_per_node = self.compute_requirement_per_node(allocation, job)
            
        for i in range(len(self.compute_nodes)):
            if not self.compute_nodes[i].can_host_job(cpu_per_node[i], gpu_per_node[i]):
                return float('inf')
            power_consumption += self.compute_nodes[i].performance.compute_current_power_consumption(self.compute_nodes[i].used_cpu + cpu_per_node[i], self.compute_nodes[i].used_gpu + gpu_per_node[i])
        
        return power_consumption

    def compute_requirement_per_node(self, allocation, job):
        cpu_per_node = [0 for i in range(len(self.compute_nodes))]
        gpu_per_node = [0 for i in range(len(self.compute_nodes))]
        bw_per_node = [0 for i in range(len(self.compute_nodes))]
        
        for i in range(len(allocation)):
            cpu_per_node[allocation[i]] += job["NN_cpu"][i]
            gpu_per_node[allocation[i]] += job["NN_gpu"][i]
            bw_per_node[allocation[i]] += job["NN_data_size"][i]
        
        return cpu_per_node, gpu_per_node
        
    def compute_allocation(self, job):
        global best_allocation
        
        additional_cpu = [0 for i in range(len(self.compute_nodes))]
        
        for i, j_req in enumerate(job["NN_cpu"]):
            node_scores = []
            for id, n in enumerate(self.compute_nodes):
                if n.can_host_job(j_req + additional_cpu[id], 0):
                    node_scores.append(n.initial_cpu - n.used_cpu)
                else:
                    node_scores.append(-1)
            
            best_score = -1
            best_location = -1
            for id, s in enumerate(node_scores):
                if s > best_score:
                    best_score = s
                    best_location = id
            
            if best_location != -1:
                best_allocation[i] = best_location
                additional_cpu[best_location] += j_req
            else: 
                return