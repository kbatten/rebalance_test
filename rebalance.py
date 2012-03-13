#!/usr/bin/env python

import sys
import subprocess
import json
import ConfigParser

#[global]
#port:8091
#
#[10.1.2.99]
#ip:localhost
#port:9000
#
#[servers]
#1:10.1.2.99
#2:10.1.2.100
#3:10.1.2.101
#4:10.1.2.102
#5:10.1.2.103
#
#[membase]
#rest_username:Administrator
#rest_password:password

python = sys.executable
cli = "/opt/couchbase/lib/python/couchbase-cli"
bucket = "default"
verbose = False

def usage():
    print "./rebalance.py <inifile> <master:port> <num_in> <num_out> [phase_hint]"
    print ""
    print " inifile            the standard testrunner ini with all nodes listed (base nodes + number rebalance in + number rebalance out"
    print " num_in             number of nodes to rebalance in (chooses from the end of the server list)"
    print " num_out            number of nodes to rebalance out (chooses from the start of the server list)"
    print " phase_hint         1: remove nodes from the end of the list, 2: remove nodes from the start of the list"
    print ""
    print " assuming we start with 24 nodes:"
    print "./rebalance.py nodes.ini master:port 24 12 1"
    print "./rebalance.py nodes.ini master:port 12 12 2"
    print "./rebalance.py nodes.ini master:port 12 0"
    print """24 nodes -> (add 24 new nodes and remove 12 existing nodes) -> 36 nodes
36 nodes -> (add 12 nodes with upgraded RAM that were removed  and remove 12 existing nodes with lower RAM size) -> 36 nodes
36 nodes -> (add 12 nodes with upgraded RAM that were removed in previous rebalance)  -> 48 nodes"""
    sys.exit()


def run_cmd(cmd):
    rtn = ""
    p = subprocess.Popen(cmd,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    stdoutdata,stderrdata=p.communicate()
    rtn += stdoutdata
    return rtn

def servers_diff(servers1, servers2):
    diff = []
    for server in servers1:
        if server not in servers2:
            diff.append(server)
    for server in servers2:
        if server not in servers1:
            diff.append(server)
    return list(set(diff))

def _vbucket_diff(original_vbuckets, new_vbuckets, index):
    rtn = ""
    numvbuckets = len(original_vbuckets)
    moved_vbuckets = 0
    created_vbuckets = 0
    deleted_vbuckets = 0

    for i in range(numvbuckets):
        if original_vbuckets[i][index] == "" and new_vbuckets[i][index] != "":
            created_vbuckets += 1
        elif original_vbuckets[i][index] != "" and new_vbuckets[i][index] == "":
            deleted_vbuckets += 1
        elif original_vbuckets[i][index] != new_vbuckets[i][index]:
            if verbose:
                rtn += `i` + " " + original_vbuckets[i][index] + " -> " + new_vbuckets[i][index] + "\n"
            moved_vbuckets += 1

    if index == 0:
        rtn += "moved   " + `moved_vbuckets` + " vbuckets"
    else:
        rtn += "moved   " + `moved_vbuckets` + " replica vbuckets" + "\n"
        rtn += "created " + `created_vbuckets` + " replica vbuckets" + "\n"
        rtn += "deleted " + `deleted_vbuckets` + " replica vbuckets"
    

    return rtn

def vbucket_active_diff(original_vbuckets, new_vbuckets):
    return _vbucket_diff(original_vbuckets, new_vbuckets, 0)

def vbucket_replica_diff(original_vbuckets, new_vbuckets):
    return _vbucket_diff(original_vbuckets, new_vbuckets, 1) + " replicas"


class Server(object):
    def __init__(self, hostname, rest_port, rest_username, rest_password):
        self.hostname = hostname
        self.rest_port = rest_port
        self.rest_username = rest_username
        self.rest_password = rest_password

    def __str__(self):
        return "{0}:{1}".format(self.hostname, self.rest_port)

    def __repr__(self):
        return self.__str__()

    def __eq__(self, other):
        return self.hostname == other.hostname and self.rest_port == other.rest_port

    def server_list(self):
        servers = []
        cmd = python + " " + cli + " server-list -c {0}:{1} -u {2} -p {3}".format(self.hostname,
                                                                                  self.rest_port,
                                                                                  self.rest_username,
                                                                                  self.rest_password)

        servers_str = run_cmd(cmd)
        for server in servers_str.split("\n"):
            if server:
                hostname = server.split(" ")[1].split(":")[0]
                port = server.split(" ")[1].split(":")[1]
                servers.append(Server(hostname, port, self.rest_username, self.rest_password))

        return servers

    def rebalance(self, servers_add, servers_remove):
        cmd = python + " " + cli
        cmd += " rebalance -c {0}:{1} -u {2} -p {3}".format(self.hostname,
                                                            self.rest_port,
                                                            self.rest_username,
                                                            self.rest_password)

        for server in servers_add:
            cmd += " --server-add={0}:{1} --server-add-username={2} --server-add-password={3}".format(server.hostname,
                                                                                                      server.rest_port,
                                                                                                      server.rest_username,
                                                                                                      server.rest_password)

        for server in servers_remove:
            cmd += " --server-remove={0}:{1}".format(server.hostname,
                                                     server.rest_port)

        run_cmd(cmd)

    def vbucket_map(self):
        cmd = python + " " + cli
        cmd += " bucket-list -c {0}:{1} -u {2} -p {3}".format(self.hostname,
                                                              self.rest_port,
                                                              self.rest_username,
                                                              self.rest_password)

        cmd += " -o json"

        bucket_json = run_cmd(cmd)
        bucket_info = json.loads(bucket_json)

        for item in bucket_info:
            if "name" in item and item["name"] == bucket:
                serverlist = item["vBucketServerMap"]["serverList"]
                vbucketmap = item["vBucketServerMap"]["vBucketMap"]
                break

        vbucket_server_map = []
        for vbucket in vbucketmap:
            vbucket_server = []
            for index in vbucket:
                if index >= 0:
                    vbucket_server.append(serverlist[index])
                else:
                    vbucket_server.append("")
            vbucket_server_map.append(vbucket_server)

        return vbucket_server_map


class Config(object):
    def __init__(self, inifile, master, num_in, num_out, phase_hint=0):
        self.servers = []
        self.master = None
        self.num_in = int(num_in)
        self.num_out = int(num_out)
        self.phase_hint = int(phase_hint)

        config = ConfigParser.ConfigParser()
        config.read(inifile)

        servers_map = {}
        master_ip = master.split(":")[0]
        master_port = master.split(":")[1]
        default_rest_port = 8091
        rest_username = ""
        rest_password = ""

        if config.has_option('global', 'port'):
            default_rest_port = config.get('global', 'port')

        if config.has_option('membase', 'rest_username'):
            rest_username = config.get('membase', 'rest_username')
        if config.has_option('membase', 'rest_password'):
            rest_password = config.get('membase', 'rest_password')

        for server in config.options('servers'):
            server_name = config.get('servers',server)
            server_id = int(server[0])
            server_ip = server_name
            server_port = default_rest_port
            if config.has_section(server_name):
                if config.has_option(server_name, 'ip'):
                    server_ip = config.get(server_name, 'ip')
                if config.has_option(server_name, 'port'):
                    server_port = config.get(server_name, 'port')

            server_info = Server(server_ip, server_port, rest_username, rest_password)
            servers_map[server_id] = server_info
            if server_ip == master_ip and server_port == master_port:
                self.master = server_info

        # sort the servers based on their index in the ini file
        for index,server in servers_map.iteritems():
            self.servers.append(server)


if __name__ == "__main__":
    if len(sys.argv) < 5:
        usage()

    if len(sys.argv) == 6:
        phase_hint = sys.argv[5]
    else:
        phase_hint = 0

    config = Config(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], phase_hint)

    # get current vbucket state
    original_vbuckets = config.master.vbucket_map()

    # get current servers, and current unclustered servers
    current_servers = config.master.server_list()
    extra_servers = servers_diff(config.servers, current_servers)

    # determine which servers to add and which to remove
    servers_add = extra_servers[:config.num_in]
    if config.phase_hint == 1:
        print "phase 1"
        servers_remove = config.servers[config.num_out:config.num_out*2]
    elif config.phase_hint == 2:
        print "phase 2"
        servers_remove = config.servers[:config.num_out]
    else:
        servers_remove = current_servers[:config.num_out]

    print "adding {0} nodes".format(sys.argv[3])
    for server in servers_add:
        print " " + `server`
    print "removing {0} nodes".format(sys.argv[4])
    for server in servers_remove:
        print " " + `server`

    # rebalane in/out
    config.master.rebalance(servers_add, servers_remove)

    # get new master if needed
    if config.master in servers_remove:
        if servers_add:
            config.master = servers_add[0]
        else:
            config.master = servers_diff(current_servers, servers_remove + [config.master])[0]
        print "new master:", config.master

    # get new vbucket state
    new_vbuckets = config.master.vbucket_map()

    print vbucket_active_diff(original_vbuckets, new_vbuckets)
    print vbucket_replica_diff(original_vbuckets, new_vbuckets)

    