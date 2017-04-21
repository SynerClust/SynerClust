#!/usr/bin/env python

import sys
import os
# import NJ
import pickle
import networkx as nx
import NetworkX_Extension as nxe
import numpy
import logging
# import subprocess
import argparse
import time
import math
from operator import itemgetter

DEVNULL = open(os.devnull, 'w')
BEST_HIT_PROPORTION_THRESHOLD = 0.90
SYNTENY_THRESHOLD = 0.3


def usage():
	print """From the rough cluster trees generated by WF_MakeRoughClusters, refine clusters so that all duplication events (paralogs) \
	occur after speciation from the most recent common ancestor or MRCA, which is [node]. [node_dir] is the directory that contains all \
	data about [node]. [flow_id] refers to a step in the workflow; [jobs_per_cmd] is the number of consensus sequence computations \
	distributed to a single node.

	[alpha], [gamma], [gain], and [loss] are parameters that impact the rooting of a tree

	WF_RefineClusters.py [node_dir] [flow_id] [jobs_per_cmd] [node] [alpha] [gamma] [gain] [loss] [children...]
	"""
	sys.exit(1)


def main():
	usage = "usage: WF_RefineCluster_leaf_centroid_newmatrix.py [options]"
	parser = argparse.ArgumentParser(usage)
	parser.add_argument('-dir', dest="node_dir", required=True, help="Path to the \"nodes\" folder. (Required)")
	parser.add_argument('-node', dest="node", required=True, help="Current node name. (Required)")
	parser.add_argument('-alpha', type=float, dest="alpha", required=True, help="Homology weight. (Required)")
	parser.add_argument('-beta', type=float, dest="beta", required=True, help="Synteny weight. (Required)")
	parser.add_argument('-gamma', type=float, dest="gamma", required=True, help="Gain/Loss weight. (Required)")
	parser.add_argument('-gain', type=float, dest="gain", required=True, help="Duplication rate for Poisson distribution. (Required)")
	parser.add_argument('-loss', type=float, dest="loss", required=True, help="Deletion rate for Poisson distribution. (Required)")
	parser.add_argument('--no-synteny', dest="synteny", default=True, action='store_false', required=False, help="Disable use of synteny (required is information not available).")
	parser.add_argument('children', nargs=2, help="Children nodes. (Required)")
	args = parser.parse_args()

	repo_path = args.node_dir[:-6]
	mrca = args.node

	my_dir = args.node_dir + mrca + "/"

	if "CLUSTERS_REFINED" in os.listdir(my_dir):
		sys.exit(0)

	FORMAT = "%(asctime)-15s %(levelname)s %(module)s.%(name)s.%(funcName)s at %(lineno)d :\n\t%(message)s\n"
	logger = logging.getLogger()
	logging.basicConfig(filename=my_dir + 'RefineClusters_leaf_centroid.log', format=FORMAT, filemode='w', level=logging.DEBUG)
	# add a new Handler to print all INFO and above messages to stdout
	ch = logging.StreamHandler(sys.stdout)
	ch.setLevel(logging.INFO)
	logger.addHandler(ch)
	logger.info('Started')

	TIMESTAMP = time.time()

	# read trees, resolve clusters
	# tree_dir = my_dir + "trees/"
	cluster_dir = my_dir + "clusters"
	if "clusters" in os.listdir(my_dir):
		if "old" not in os.listdir(my_dir):
			os.system("mkdir " + my_dir + "old")

		os.system("mv -f " + cluster_dir + "/ " + my_dir + "old/")
	os.system("mkdir " + cluster_dir)
	cluster_dir = cluster_dir + "/"

	cluster_counter = 1  # used to number clusters
	synteny_data = {}
	pickleSeqs = {}
	pickleToCons = {}
	singletons_pep = {}
	pickleMaps = {}
	# picklePeps = {}
	# childrenpkls = {}
	children_cons = {}
	old_potentials = {}
	# print "last_tree", last_tree
	# load locus_mapping files from children
	for c in args.children:
		with open(args.node_dir + c + "/locus_mappings.pkl", 'r') as pklFile:
			pickleMaps[c] = pickle.load(pklFile)
		if args.synteny:
			with open(args.node_dir + c + "/synteny_data.pkl", 'r') as pklFile:
				synteny_data[c] = pickle.load(pklFile)
		if c[0] == "L":
			with open(args.node_dir + c + "/" + c + ".pkl", "r") as f:
				children_cons[c] = pickle.load(f)
			# 	childrenpkls[c] = pickle.load(f)
			# children_cons[c] = childrenpkls[c]
		else:  # c[0] == "N"
			with open(args.node_dir + c + "/consensus_data.pkl", "r") as f:
				children_cons[c] = pickle.load(f)
			with open(args.node_dir + c + "/potential_inparalogs.pkl", "r") as f:
				old_potentials.update(pickle.load(f))
			# with open(args.node_dir + c + "/pep_data.pkl", "r") as f:
			# 	childrenpkls[c] = pickle.load(f)
			# with open(args.node_dir + c + "/singletons_pep_data.pkl", "r") as f:
			# 	childrenpkls[c].update(pickle.load(f))

	blast_pep = {}
	for c in args.children:
		my_blast_pep = open(my_dir + c + ".blast.fa", 'r').readlines()
		curBlast = ""
		curPep = ""
		for m in my_blast_pep:
			m = m.rstrip()
			if len(m) < 1:
				continue
			if m.find(">") > -1:
				if len(curBlast) > 0:
					blast_pep[curBlast].append(curPep)
					curPep = ""
				line = m[1:]
				curBlast = line.split(";")[0]
				if curBlast not in blast_pep:
					blast_pep[curBlast] = []
			else:
				curPep += m
				# blast_pep[curBlast] += m
		if len(curPep) > 0:
			blast_pep[curBlast].append(curPep)

	newPickleMap = {}  # this will turn into the locus mappings for this node
	if args.synteny:
		newSyntenyMap = {}
	newNewickMap = {"children": [set(args.children)]}
	# special_pep = {}
	childToCluster = {}  # child gene/og --> og.id for this node

	# make control files for consensus sequence formation
	# cons_cmds = []
	cons_pkl = {}
	singletons = cluster_dir + "singletons.cons.pep"
	singles = open(singletons, 'w')
	sum_stats = my_dir + "summary_stats.txt"
	sstats = open(sum_stats, 'w')

# 	old_orphans = open(tree_dir + "orphan_genes.txt", 'r').readlines()
# 	orphans = open(tree_dir + "orphan_genes.txt", 'r').readlines()
	# orphans = []
	ok_trees = []

	if args.synteny:
		with open(repo_path + "nodes/" + args.node + "/trees/gene_to_cluster.pkl", "r") as f:
			gene_to_rough_cluster = pickle.load(f)
	graphs = {}
	with open(repo_path + "nodes/" + args.node + "/trees/cluster_graphs.dat", "r") as f:
		to_parse = []
		clusterID = None
		for line in f:
			if line == "//\n":
				if to_parse:
					graphs[clusterID] = nx.parse_edgelist(to_parse, create_using=nx.DiGraph(), nodetype=str)
				to_parse = []
				clusterID = None
			else:
				if clusterID:
					to_parse.append(line.rstrip())
				else:
					clusterID = line.rstrip()

	cluster_counter = 1
	ok_trees = []
	genes_to_cluster = {}  # not to mistake with gene_to_cluster that contains rough clustering for synteny calculation

	with open(repo_path + "nodes/" + args.node + "/trees/orphan_genes.txt", "r") as f:
		for line in f:
			node = line.rstrip()
			new_orphan = "%s_%06d" % (mrca, cluster_counter)
			cluster_counter += 1
			ok_trees.append((new_orphan, (node,), (node, node)))  # (node,) comma is required so its a tuple that can be looped on and not on the string itself
			genes_to_cluster[node] = (new_orphan, False)

	potentials = {}  # potential inparalogs

	logger.debug("Loading files took " + str(time.time() - TIMESTAMP))
	TIMESTAMP = time.time()

# 	for clusterID in pickleSeqs:
	# for cluster in cluster_to_genes:

	for cluster in graphs:
		TIMESTAMP = time.time()

		graph = graphs[cluster]

		if args.synteny:
			leaves = graph.nodes()
			leaves.sort()
			syn = {}
			for n in leaves:  # genes
				syn[n] = []
				leaf = "_".join(n.split("_")[:-1])
				for m in synteny_data[leaf][n]['neighbors']:
					syn[n].append(gene_to_rough_cluster[m])
			syn_matrix = numpy.empty(len(leaves) * (len(leaves) - 1) / 2)
			i = 1
			pos = 0
			for m in leaves[1:]:
				syn_m = set(syn[m])
				syn_m.discard(cluster)
				mSeqs = len(syn[m]) - syn[m].count(cluster)
				for n in leaves[:i]:
					nSeqs = len(syn[n]) - syn[n].count(cluster)
					matches = 0
					if mSeqs == 0 or nSeqs == 0:
						syn_matrix[pos] = 1.0  # no neighbors in common if someone has no neighbors  # -= 0 ? does it change anything?
						pos += 1
						continue
					all_neighbors = syn_m & set(syn[n])  # no need to .discard(cluster) since already did in syn_m, so won't be present in union
					for a in all_neighbors:
						t_m = max(syn[m].count(a), 0)
						t_n = max(syn[n].count(a), 0)
						matches += min(t_m, t_n)
					# synFrac = float(matches) / float(max(mSeqs, nSeqs))
					synFrac = float(matches) / float(mSeqs + nSeqs)
					# synFrac = float(matches) / float(max_neighbors_count)
					syn_matrix[pos] = 1.0 - synFrac
					pos += 1
				i += 1

			logger.debug("Built matrices for " + cluster + " in " + str(time.time() - TIMESTAMP))
			# formatting matrix for output
			i = 0
			j = 1
			syn_buff = leaves[0] + "\n" + leaves[1] + "\t"
			for y in numpy.nditer(syn_matrix):
				syn_buff += str(y) + "\t"
				i += 1
				if i >= j:
					i = 0
					j += 1
					if j < len(leaves):
						syn_buff += "\n" + leaves[j] + "\t"
					else:
						syn_buff += "\n"
			logger.debug("Synteny matrix for " + cluster + ":\n" + syn_buff)
			TIMESTAMP = time.time()

		# lowest_synteny = SYNTENY_THRESHOLD
		# low_positions = []
		# lowest_positions = []
		# it = numpy.nditer(syn_matrix, flags=['f_index'])
		# while not it.finished:
		# 	if it[0] <= SYNTENY_THRESHOLD:
		# 		if it[0] < lowest_synteny:
		# 			low_positions.extend(lowest_positions)
		# 			lowest_positions = [it.index]
		# 		elif it[0] == lowest_synteny:
		# 			lowest_positions.append(it.index)
		# 		else:
		# 			low_positions.append(it.index)
		# low_is = []
		# low_js = []
		# for position in low_positions:
		# 	position += 1  # formula works for indexes starting at 1, so need to offset
		# 	i = math.ceil(math.sqrt(2 * position + 0.25) - 0.5)
		# 	j = position - ((i - 1) * i / 2)
		# 	low_is.append(i - 1)  # formula is for lower triangular matrix, so need to offset distance matrix columns because we start at 0
		# 	low_js.append(j)  # no need for row offset because row 0 is empty in distance matrix

		new_graph = graph.copy()
		# check synteny matrix for cells lowest synteny (below a threshold, 0.2-0.5?)
		syntenic = []
		it = numpy.nditer(syn_matrix, flags=['f_index'])
		while not it.finished:
			if it[0] <= SYNTENY_THRESHOLD:
				position = it.index + 1  # formula works for indexes starting at 1, so need to offset
				i = math.ceil(math.sqrt(2 * position + 0.25) - 0.5)  # formula is for lower triangular matrix, so need to offset distance matrix columns because we start at 0
				j = position - ((i - 1) * i / 2)  # no need for row offset because row 0 is empty in distance matrix
				syntenic.append((it[0], it.index, i - 1, j))
			it.iternext()
		syntenic.sort(key=itemgetter(0))  # key precised so that sort is only done on first element of lists and not on other ones for potential ties

		for pair in syntenic:  # loop twice to allow pairs where best hit got pulled into another pair to be clustered on 2nd round?
			i = pair[2]
			j = pair[3]
			if not graph.has_edge(leaves[i], leaves[j]):  # if (i, j) is in the graph, (j, i) is also per construction/filtering of rough clusters; reverse is true too
				continue
			# check if this cell is the only low synteny for each member of the pair
			if len([p for p in syntenic if p[2] == i or p[3] == i or p[2] == j or p[3] == j]) == 1:
				# if yes, check if RBH hits, or among best hits
				if graph[leaves[i]][leaves[j]]['rank'] + graph[leaves[j]][leaves[i]]['rank'] <= 4:  # 2 = RBH, put 3 or 4 as limit?
					# if yes, cluster
					# merge leaves[i] and leaves[j]
					syn_dist = ":" + str(pair[0] / 2.0)
					new_node = "%s_%06d" % (mrca, cluster_counter)
					cluster_counter += 1
					ok_trees.append((new_node, (leaves[i], leaves[j]), ("(" + leaves[i] + ":" + graph[leaves[i]][leaves[j]]['rank'] + "," + leaves[j] + ":" + graph[leaves[j]][leaves[i]]['rank'] + ")", "(" + leaves[i] + syn_dist + "," + leaves[j] + syn_dist + ")")))
					nxe.merge(new_graph, graph, leaves[i], leaves[j], new_node)
					genes_to_cluster[leaves[i]] = (new_node, True)
					genes_to_cluster[leaves[j]] = (new_node, True)
					# remove other edges pointing to those nodes
					graph.remove_node(leaves[i])
					graph.remove_node(leaves[j])
			# if one of the genes has more than 1 syntenic gene, but still RBH
			# elif graph[leaves[i]][leaves[j]]['rank'] + graph[leaves[j]][leaves[i]]['rank'] == 2:   # this can probably be done by following else?? since first if for each of leaves i/j checks for the same thing overall
			# 	##### MERGE leaves[i] and leaves[j]
			# 	# remove other edges pointing to those nodes
			# 	nxe.merge(new_graph, leaves[i], leaves[j], "merged_node_" + str(count))
			# 	count += 1
			# 	graph.remove_node(leaves[i])
			# 	graph.remove_node(leaves[j])
			else:
				# if best hit for ones for which it isn't have -m close, cluster
				## !! check first if best hit hasn't been clustered
				good = 0
				if graph[leaves[i]][leaves[j]]['rank'] == 1:
					good += 1
				elif max([f['rank'] for f in graph[leaves[i]].values()]) == graph[leaves[i]][leaves[j]]['rank']:  # best hit has been clustered, this is the best remaining hit
					good += 1
				elif [f for f in graph[leaves[i]].values() if f['rank'] == 1]:  # if best hit hasn't been clustered
					if graph[leaves[i]][leaves[j]]['m'] >= BEST_HIT_PROPORTION_THRESHOLD:
						good += 1
				if graph[leaves[j]][leaves[i]]['rank'] == 1:
					good += 1
				elif max([f['rank'] for f in graph[leaves[j]].values()]) == graph[leaves[j]][leaves[i]]['rank']:
					good += 1
				elif [f for f in graph[leaves[j]].values() if f['rank'] == 1]:  # if best hit hasn't been clustered
					if graph[leaves[j]][leaves[i]]['m'] >= BEST_HIT_PROPORTION_THRESHOLD:
						good += 1
				# if graph[leaves[i]][leaves[j]]['m'] >= BEST_HIT_PROPORTION_THRESHOLD and graph[leaves[j]][leaves[i]]['m'] >= BEST_HIT_PROPORTION_THRESHOLD:
				if good == 2:
					# merge leaves[i] and leaves[j]
					syn_dist = ":" + str(pair[0] / 2.0)
					new_node = "%s_%06d" % (mrca, cluster_counter)
					cluster_counter += 1
					ok_trees.append((new_node, (leaves[i], leaves[j]), ("(" + leaves[i] + ":" + graph[leaves[i]][leaves[j]]['rank'] + "," + leaves[j] + ":" + graph[leaves[j]][leaves[i]]['rank'] + ")", "(" + leaves[i] + syn_dist + "," + leaves[j] + syn_dist + ")")))
					nxe.merge(new_graph, graph, leaves[i], leaves[j], new_node)
					genes_to_cluster[leaves[i]] = (new_node, True)
					genes_to_cluster[leaves[j]] = (new_node, True)
					# remove other edges pointing to those nodes
					graph.remove_node(leaves[i])
					graph.remove_node(leaves[j])
		# check for remaining RBH and cluster
		# edges = graph.edges()    # replace with nodes that still have edges
		# i = 0
		# while i < len(edges):
		# 	e = edges[i]

		i = 0
		nodes_left = [n for n in graph.nodes() if graph[n]]  # nodes left that still have edges connecting them to other nodes
		while i < len(nodes_left):
			n1 = nodes_left[i]
			pair = None
			# if e[0][:32] != e[1][:32] and graph.has_edge(e[0], e[1]):  # don't merge self-hits from leaves, and check that it's not 2nd edge from an already merged pair or edge with a removed by merging node
			targets = [n2 for n2 in graph[n1] if graph[n1][n2]['rank'] == 1 and graph[n2][n1]['rank'] and n1[:32] != n2[:32]]  # RBH, and don't merge self-hits from leaves
			if len(targets) == 0:
				i += 1
				continue
			if len(targets) > 1:
				pairs = []
				for n2 in targets:
					ii = leaves.index(n1)
					jj = leaves.index(n2)
					syn = 1.0
					if ii < jj:
						syn = syn_matrix[(jj * (jj - 1) / 2) + ii]
					else:
						syn = syn_matrix[(ii * (ii - 1) / 2) + jj]
					pairs.append([n2, syn])  # target, synteny
				pairs.sort(key=itemgetter(1))  # sort by ascending synteny distance
				if pairs[0][1] < 1.0 and pairs[0][1] != pairs[1][1]:  # synteny evidance and no ex-aequo
					# CHECK IF THE 2ND NODE ALSO HAS THE LOWEST SYNTENY WITH THE CURRENT NODE
					# CHECK SYNTENY MATRIX AT 2ND NODE VALUES FIRST? REVERT INDEX TO CHECK IF EDGE EXISTS AND GOOD HIT?
					likely_pair = pairs[0][0]
					targets2 = [n2 for n2 in graph[likely_pair] if graph[likely_pair][n2]['rank'] == 1 and graph[n2][likely_pair]['rank'] == 1 and likely_pair[:32] != n2[:32]]
					if targets2 > 1:  # else it is the only hit so good
						pairs2 = []
						for n2 in targets2:
							ii = leaves.index(n1)
							jj = leaves.index(n2)
							syn = 1.0
							if ii < jj:
								syn = syn_matrix[(jj * (jj - 1) / 2) + ii]
							else:
								syn = syn_matrix[(ii * (ii - 1) / 2) + jj]
							pairs2.append([n2, syn])  # target, synteny
						pairs2.sort(key=itemgetter(1))  # sort by ascending synteny distance
						if pairs2[0][0] == n1 and pairs2[0][1] != pairs2[1][1]:  # synteny evidance to 1st node and no ex-aequo
							pair = pairs[0][0]
						else:  # best node to merge from n1 side is not the best from n2 side
							i += 1
							continue
					else:
						pair = pairs[0][0]
				else:  # no evidance of which node is the good one to merge to
					i += 1
					continue
			else:
				pair = targets[0]
				# if graph[e[0]][e[1]]['rank'] == 1 and graph[e[1]][e[0]]['rank'] == 1:
				# MERGE e[0] and e[1]
			ii = leaves.index(n1)
			jj = leaves.index(pair)
			ma = max(ii, jj)
			mi = min(ii, jj)
			pos = (ma * (ma - 1) / 2) + mi
			syn_dist = ":" + str(syn_matrix[pos] / 2.0)
			new_node = "%s_%06d" % (mrca, cluster_counter)
			cluster_counter += 1
			ok_trees.append((new_node, (n1, pair), ("(" + n1 + ":1," + pair + ":1)", "(" + n1 + syn_dist + "," + pair + syn_dist + ")")))
			nxe.merge(new_graph, graph, n1, pair, new_node)
			genes_to_cluster[n1] = (new_node, True)
			genes_to_cluster[pair] = (new_node, True)
			# remove other edges pointing to those nodes
			graph.remove_node(n1)
			graph.remove_node(pair)
			if nodes_left.index(pair) < i:
				i -= 1
			nodes_left.remove(n1)
			nodes_left.remove(pair)
			# del edges[i]  # edges.remove(e)
			# i -= 1
			# edges.remove((pair, n1))  # no need to i -= 1 because reciprocity implies the first edge of the pair encountered will trigger the merging
			# i += 1

		# check remaining, is there any match in between them directly, any synteny?
		# remaining = all nodes in graph, check what are their edges in new_graph = potential inparalogs
			# if none, keep as potential inparalogs but don't cluster

		for node in new_graph.nodes():
			if mrca not in node:
				if node not in genes_to_cluster:
					new_orphan = "%s_%06d" % (mrca, cluster_counter)
					cluster_counter += 1
					genes_to_cluster[node] = (new_orphan, False)
				else:
					new_orphan = genes_to_cluster[node][0]
				(k, v) = min([[f, new_graph[node][f]['rank']] for f in new_graph[node]], key=itemgetter(1))
				# for k in new_graph[node].keys():
				if mrca in k:
					if new_orphan not in potentials:
						potentials[new_orphan] = set([k])
					else:  # never?
						potentials[new_orphan].add(k)
					# potentials.append((new_orphan, k))
				elif node[:32] == k[:32]:  # self hit, possible for full species tree leaves only
					if k not in genes_to_cluster:
						new_orphan2 = "%s_%06d" % (mrca, cluster_counter)
						cluster_counter += 1
						genes_to_cluster[k] = (new_orphan2, False)
					else:
						new_orphan2 = genes_to_cluster[k][0]
					if new_orphan not in potentials:
						potentials[new_orphan] = set([new_orphan2])
					else:  # never?
						potentials[new_orphan].add(new_orphan2)
					# potentials.append((new_orphan, new_orphan2))
				# elif node[:32] != n[:32]:  # from both children, not the same  # else self blast so leaves?
				# 	potentials.append(n)
				ok_trees.append((new_orphan, (node,), (node, node)))  # (node,) comma is required so its a tuple that can be looped on and not on the string itself

	# if args.synteny:
	# 	for o in orphans:
	# 		ok_trees.insert(0, [[o.rstrip()], [o.rstrip(), o.rstrip()], True])
	# else:
	# 	for o in orphans:
	# 		ok_trees.insert(0, [[o.rstrip()], [o.rstrip(), ""], True])

	in_paralogs = {}
	for old in old_potentials:
		if genes_to_cluster[old][1] is False:  # gene is still in an orphan cluster
			# potentials.append((genes_to_cluster[old[0]][0], genes_to_cluster[old[1]][0]))
			# in_paralogs.append((genes_to_cluster[old[0]][0], genes_to_cluster[old[1]][0]))
			if genes_to_cluster[old][0] not in in_paralogs:
				in_paralogs[genes_to_cluster[old][0]] = set([genes_to_cluster[g][0] for g in old_potentials[old]])
			else:
				in_paralogs[genes_to_cluster[old][0]].update([genes_to_cluster[g][0] for g in old_potentials[old]])

	for (k, v) in in_paralogs.items():
		if k not in potentials:
			potentials[k] = v
		else:
			potentials[k].update(v)
	# potentials.extend(in_paralogs)

	for ok in ok_trees:
		# c = str(cluster_counter)
		# clusterID = ""
		# while len(c) < 6:
		# 	c = "0" + c
		# clusterID = mrca + "_" + c
		clusterID = ok[0]
		newPickleMap[clusterID] = []
		if args.synteny:
			newSyntenyMap[clusterID] = {'count': 0, 'neighbors': [], 'children': []}

		# get list of leaf sequences to pull and organize in treeSeqs
		treeSeqs = {}
		tree_seq_count = 0
		# leafSeqs = {}
		child_leaves = {}
		taxa = set([])
		taxa_map = {}
		for g in ok[1]:
			child = "_".join(g.split("_")[:-1])
			if args.synteny:
				newSyntenyMap[clusterID]['children'].append(g)
			childToCluster[g] = clusterID
			leafKids = pickleMaps[child][g]
			if child not in child_leaves:
				child_leaves[child] = 0
			child_leaves[child] += len(leafKids)
# TODO in this part, children pickle are opened every time, could probably only open each one
			for l in leafKids:
				newPickleMap[clusterID].append(l)
				lKid = "_".join(l.split("_")[:-1])
				taxa.add(lKid)
				if lKid not in taxa_map:
					taxa_map[lKid] = 0
				taxa_map[lKid] += 1
				if lKid not in pickleSeqs:
					seqFile = args.node_dir + lKid + "/" + lKid + ".pkl"
					pklFile = open(seqFile, 'rb')
					pickleSeqs[lKid] = pickle.load(pklFile)
					pklFile.close()
				seq = pickleSeqs[lKid][l]
				if seq not in treeSeqs:
					treeSeqs[seq] = []
				treeSeqs[seq].append(l)
				tree_seq_count += 1
				if args.synteny:
					newSyntenyMap[clusterID]['count'] += 1
		newNewickMap[clusterID] = list(ok[2])

		my_lengths = []
		min_taxa = len(taxa)
		max_taxa = 0
		for tm in taxa_map:
			tm_val = taxa_map[tm]
			if tm_val > max_taxa:
				max_taxa = tm_val
			if tm_val < min_taxa:
				min_taxa = tm_val
		for seq in treeSeqs:
			for me in treeSeqs[seq]:
				my_lengths.append(len(seq))
		avg = numpy.average(my_lengths)
		std = numpy.std(my_lengths)
		std_avg = std / avg
		out_dat = [clusterID, str(len(my_lengths)), str(len(taxa)), str(min_taxa), str(max_taxa), str(min(my_lengths)), str(max(my_lengths)), str(avg), str(std), str(std_avg)]

# 		sys.exit()
		sstats.write("\t".join(out_dat) + "\n")

		if len(ok[1]) == 1:
			child = "_".join(ok[1][0].split("_")[:-1])
# 			seq = children_cons[child][ok[0][0]]
			seqs = {}
			if child[0] == "L":
				seqs[g] = children_cons[child][g]
			else:
				for seq in children_cons[child][g]:
					i = 0
					identifier = None
					for s in seq.rstrip().split("\n"):
						if not i % 2:
							identifier = s[1:].split(";")[0]
						else:
							seqs[identifier] = s
						i += 1
# 			else:
				# need to get list of sequences to write them all
			for k, s in seqs.iteritems():
				cons_pkl[clusterID] = [">" + clusterID + ";" + str(len(s)) + "\n" + s + "\n"]
				singletons_pep[clusterID] = [">" + clusterID + ";" + str(len(s)) + "\n" + s + "\n"]
				singles.write(">" + clusterID + ";" + str(len(s)) + "\n" + s + "\n")
		else:
			pickleToCons[clusterID] = []
			# newNewickMap[clusterID].append([])
			for g in ok[1]:
				child = "_".join(g.split("_")[:-1])
				seqs = {}
				if child[0] == "L":
					seqs[g] = children_cons[child][g]
				else:
					for seq in children_cons[child][g]:
						# if seq[0] == ">":  # else its a leaf so only sequence is present
						i = 0
						identifier = None
						for s in seq.rstrip().split("\n"):
							if not i % 2:  # not so that 0 is True
								identifier = s[1:].split(";")[0]
							else:
								seqs[identifier] = s
							i += 1
# 						else:
# 							seqs = [seq]
				i = 0
				for k, s in seqs.iteritems():
					pickleToCons[clusterID].append(">" + k + ";" + str(i) + ";" + str(len(s)) + "\n" + s + "\n")  # str(i) is a unique part in name so that all different names for muscle/fasttree
					# newNewickMap[clusterID][2].append(">" + k + ";" + str(len(s)) + "\n" + s + "\n")
					i += 1
		# cluster_counter += 1
	singles.close()
	sstats.close()

	pklPep = my_dir + "pep_data.pkl"
	sdat = open(pklPep, 'wb')
	pickle.dump(pickleToCons, sdat)
	sdat.close()

	with open(my_dir + "singletons_pep_data.pkl", "w") as f:
		pickle.dump(singletons_pep, f)

	# update synteny data
	if args.synteny:
		for clust in newSyntenyMap:
			for child in newSyntenyMap[clust]['children']:
				lc = "_".join(child.split("_")[:-1])
				# logger.debug("%s splitted to %s" % (child, lc))
				for neigh in synteny_data[lc][child]['neighbors']:
					# logger.debug("newSyntenyMap[%s]['neighbors'].append(childToCluster[%s]" % (clust, neigh))
					newSyntenyMap[clust]['neighbors'].append(childToCluster[neigh])
		# pickle synteny data
		pklSyn = my_dir + "synteny_data.pkl"
		sdat = open(pklSyn, 'wb')
		pickle.dump(newSyntenyMap, sdat)
		sdat.close()

	# pickle the locus mappings
	pklMap = my_dir + "locus_mappings.pkl"
	sdat = open(pklMap, 'wb')
	pickle.dump(newPickleMap, sdat)
	sdat.close()

	with open(my_dir + "clusters_newick.pkl", "w") as f:
		pickle.dump(newNewickMap, f)

	with open(my_dir + "consensus_data.pkl", "w") as f:
		pickle.dump(cons_pkl, f)

	with open(my_dir + "potential_inparalogs.pkl", "w") as f:
		pickle.dump(potentials, f)

	with open(my_dir + "current_inparalogs.pkl", "w") as f:
		pickle.dump(in_paralogs, f)

	# script complete call
	clusters_done_file = my_dir + "CLUSTERS_REFINED"
	cr = open(clusters_done_file, 'w')
	cr.write("Way to go!\n")
	cr.close()


if __name__ == "__main__":
	main()
