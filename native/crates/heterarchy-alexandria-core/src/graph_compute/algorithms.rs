//! Stable adjacency, SCC, traversal, lineage, orphan, and projection-diff compute.

use std::collections::{BTreeMap, BTreeSet, VecDeque};

use petgraph::algo::kosaraju_scc;
use petgraph::graph::{DiGraph, NodeIndex};

use super::{
    GraphAdjacency, GraphAnalysis, GraphComputeError, GraphCycleComponent, GraphLineageRequest,
    GraphLineageResult, GraphProjection, GraphProjectionDiff, GraphProjectionEdge,
    GraphProjectionNode, GraphTraversalRequest, GraphTraversalResult, GraphTraversalVisit,
    TraversalDirection, relation_filter,
};

pub(super) fn analyze_projection(
    projection: &GraphProjection,
    previous_projection: Option<&GraphProjection>,
    traversal_requests: &[GraphTraversalRequest],
    lineage_requests: &[GraphLineageRequest],
) -> Result<GraphAnalysis, GraphComputeError> {
    let index = GraphIndex::new(projection)?;
    let adjacency = index.adjacency();
    let orphan_note_ids = index.orphan_note_ids();
    let cycles = index.cycles();
    let traversals = traversal_requests
        .iter()
        .map(|request| index.traverse_request(request))
        .collect();
    let lineages = lineage_requests
        .iter()
        .map(|request| index.lineage_request(request))
        .collect();
    let diff = projection_diff(previous_projection, projection);
    Ok(GraphAnalysis {
        adjacency,
        orphan_note_ids,
        cycles,
        traversals,
        lineages,
        diff,
    })
}

#[derive(Debug, Clone, Copy)]
struct IndexedNeighbor<'edge> {
    node_index: usize,
    edge: &'edge GraphProjectionEdge,
}

struct GraphIndex<'projection> {
    projection: &'projection GraphProjection,
    node_lookup: BTreeMap<&'projection str, usize>,
    outgoing: Vec<Vec<IndexedNeighbor<'projection>>>,
    incoming: Vec<Vec<IndexedNeighbor<'projection>>>,
    graph: DiGraph<(), ()>,
    graph_nodes: Vec<NodeIndex>,
    self_loops: BTreeSet<usize>,
}

impl<'projection> GraphIndex<'projection> {
    fn new(projection: &'projection GraphProjection) -> Result<Self, GraphComputeError> {
        let mut node_lookup = BTreeMap::new();
        for (index, node) in projection.nodes.iter().enumerate() {
            if node_lookup.insert(node.note_id.as_str(), index).is_some() {
                return Err(GraphComputeError::new(format!(
                    "projected node identity is duplicated: {}",
                    node.note_id
                )));
            }
        }
        let mut graph = DiGraph::<(), ()>::new();
        let graph_nodes = projection
            .nodes
            .iter()
            .map(|_| graph.add_node(()))
            .collect::<Vec<_>>();
        let mut outgoing = vec![Vec::new(); projection.nodes.len()];
        let mut incoming = vec![Vec::new(); projection.nodes.len()];
        let mut self_loops = BTreeSet::new();
        for edge in &projection.edges {
            let source_index = node_lookup
                .get(edge.source_note_id.as_str())
                .copied()
                .ok_or_else(|| {
                    GraphComputeError::new(format!(
                        "projected edge {} has a missing source node {}",
                        edge.edge_id, edge.source_note_id
                    ))
                })?;
            let target_index = node_lookup
                .get(edge.target_note_id.as_str())
                .copied()
                .ok_or_else(|| {
                    GraphComputeError::new(format!(
                        "projected edge {} has a missing target node {}",
                        edge.edge_id, edge.target_note_id
                    ))
                })?;
            outgoing[source_index].push(IndexedNeighbor {
                node_index: target_index,
                edge,
            });
            incoming[target_index].push(IndexedNeighbor {
                node_index: source_index,
                edge,
            });
            graph.add_edge(graph_nodes[source_index], graph_nodes[target_index], ());
            if source_index == target_index {
                self_loops.insert(source_index);
            }
        }
        for neighbors in outgoing.iter_mut().chain(incoming.iter_mut()) {
            neighbors.sort_by(|left, right| {
                (
                    projection.nodes[left.node_index].note_id.as_str(),
                    left.edge.edge_id.as_str(),
                )
                    .cmp(&(
                        projection.nodes[right.node_index].note_id.as_str(),
                        right.edge.edge_id.as_str(),
                    ))
            });
        }
        Ok(Self {
            projection,
            node_lookup,
            outgoing,
            incoming,
            graph,
            graph_nodes,
            self_loops,
        })
    }

    fn adjacency(&self) -> Vec<GraphAdjacency> {
        self.projection
            .nodes
            .iter()
            .enumerate()
            .map(|(index, node)| GraphAdjacency {
                note_id: node.note_id.clone(),
                outgoing: distinct_neighbor_ids(self.projection, &self.outgoing[index]),
                incoming: distinct_neighbor_ids(self.projection, &self.incoming[index]),
            })
            .collect()
    }

    fn orphan_note_ids(&self) -> Vec<String> {
        self.projection
            .nodes
            .iter()
            .enumerate()
            .filter(|(index, _)| {
                self.outgoing[*index].is_empty() && self.incoming[*index].is_empty()
            })
            .map(|(_, node)| node.note_id.clone())
            .collect()
    }

    fn cycles(&self) -> Vec<GraphCycleComponent> {
        let graph_index_by_node = self
            .graph_nodes
            .iter()
            .enumerate()
            .map(|(index, node)| (*node, index))
            .collect::<BTreeMap<_, _>>();
        let mut cycles = kosaraju_scc(&self.graph)
            .into_iter()
            .filter_map(|component| {
                let mut indices = component
                    .iter()
                    .filter_map(|node| graph_index_by_node.get(node).copied())
                    .collect::<Vec<_>>();
                indices.sort_unstable();
                let self_loop = indices.len() == 1 && self.self_loops.contains(&indices[0]);
                (indices.len() > 1 || self_loop).then(|| GraphCycleComponent {
                    note_ids: indices
                        .iter()
                        .map(|index| self.projection.nodes[*index].note_id.clone())
                        .collect(),
                    self_loop,
                })
            })
            .collect::<Vec<_>>();
        for component in &mut cycles {
            component.note_ids.sort();
        }
        cycles.sort_by(|left, right| left.note_ids.cmp(&right.note_ids));
        cycles
    }

    fn traverse_request(&self, request: &GraphTraversalRequest) -> GraphTraversalResult {
        let relations = relation_filter(&request.relations);
        let traversal = self.traverse(TraversalSpec {
            start_note_id: &request.start_note_id,
            direction: request.direction,
            relations: &relations,
            max_depth: request.max_depth,
            max_results: request.max_results,
        });
        GraphTraversalResult {
            request_id: request.request_id.clone(),
            start_note_id: request.start_note_id.clone(),
            start_found: traversal.start_found,
            visits: traversal.visits,
            truncated: traversal.truncated,
        }
    }

    fn lineage_request(&self, request: &GraphLineageRequest) -> GraphLineageResult {
        let relations = BTreeSet::from(["supersedes"]);
        let supersedes = self.traverse(TraversalSpec {
            start_note_id: &request.note_id,
            direction: TraversalDirection::Outgoing,
            relations: &relations,
            max_depth: request.max_depth,
            max_results: request.max_results.saturating_add(1),
        });
        let superseded_by = self.traverse(TraversalSpec {
            start_note_id: &request.note_id,
            direction: TraversalDirection::Incoming,
            relations: &relations,
            max_depth: request.max_depth,
            max_results: request.max_results.saturating_add(1),
        });
        let note_found = supersedes.start_found || superseded_by.start_found;
        GraphLineageResult {
            request_id: request.request_id.clone(),
            note_id: request.note_id.clone(),
            note_found,
            supersedes: without_start(supersedes.visits, &request.note_id, request.max_results),
            superseded_by: without_start(
                superseded_by.visits,
                &request.note_id,
                request.max_results,
            ),
            truncated: supersedes.truncated || superseded_by.truncated,
        }
    }

    fn traverse(&self, spec: TraversalSpec<'_>) -> TraversalState {
        let Some(start_index) = self.node_lookup.get(spec.start_note_id).copied() else {
            return TraversalState::default();
        };
        let mut visits = Vec::with_capacity(spec.max_results.min(self.projection.nodes.len()));
        let mut visited = BTreeSet::from([start_index]);
        let mut queue = VecDeque::from([(start_index, 0_usize)]);
        let mut truncated = false;
        while let Some((current, depth)) = queue.pop_front() {
            visits.push(GraphTraversalVisit {
                note_id: self.projection.nodes[current].note_id.clone(),
                depth,
            });
            if visits.len() >= spec.max_results {
                truncated =
                    !queue.is_empty() || self.has_unvisited_neighbor(current, &visited, spec);
                break;
            }
            if depth >= spec.max_depth {
                truncated |= self.has_unvisited_neighbor(current, &visited, spec);
                continue;
            }
            for neighbor in self.neighbors(current, spec) {
                if visited.insert(neighbor) {
                    queue.push_back((neighbor, depth.saturating_add(1)));
                }
            }
        }
        TraversalState {
            start_found: true,
            visits,
            truncated,
        }
    }

    fn has_unvisited_neighbor(
        &self,
        current: usize,
        visited: &BTreeSet<usize>,
        spec: TraversalSpec<'_>,
    ) -> bool {
        self.neighbors(current, spec)
            .into_iter()
            .any(|neighbor| !visited.contains(&neighbor))
    }

    fn neighbors(&self, current: usize, spec: TraversalSpec<'_>) -> Vec<usize> {
        let mut neighbors = BTreeSet::new();
        if matches!(
            spec.direction,
            TraversalDirection::Outgoing | TraversalDirection::Both
        ) {
            extend_filtered_neighbors(&mut neighbors, &self.outgoing[current], spec.relations);
        }
        if matches!(
            spec.direction,
            TraversalDirection::Incoming | TraversalDirection::Both
        ) {
            extend_filtered_neighbors(&mut neighbors, &self.incoming[current], spec.relations);
        }
        let mut values = neighbors.into_iter().collect::<Vec<_>>();
        values.sort_by(|left, right| {
            self.projection.nodes[*left]
                .note_id
                .cmp(&self.projection.nodes[*right].note_id)
        });
        values
    }
}

#[derive(Clone, Copy)]
struct TraversalSpec<'filter> {
    start_note_id: &'filter str,
    direction: TraversalDirection,
    relations: &'filter BTreeSet<&'filter str>,
    max_depth: usize,
    max_results: usize,
}

#[derive(Default)]
struct TraversalState {
    start_found: bool,
    visits: Vec<GraphTraversalVisit>,
    truncated: bool,
}

fn extend_filtered_neighbors(
    destination: &mut BTreeSet<usize>,
    candidates: &[IndexedNeighbor<'_>],
    relations: &BTreeSet<&str>,
) {
    destination.extend(
        candidates
            .iter()
            .filter(|candidate| {
                relations.is_empty() || relations.contains(candidate.edge.relation.as_str())
            })
            .map(|candidate| candidate.node_index),
    );
}

fn distinct_neighbor_ids(
    projection: &GraphProjection,
    neighbors: &[IndexedNeighbor<'_>],
) -> Vec<String> {
    neighbors
        .iter()
        .map(|neighbor| projection.nodes[neighbor.node_index].note_id.as_str())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .map(str::to_owned)
        .collect()
}

fn without_start(
    visits: Vec<GraphTraversalVisit>,
    start_note_id: &str,
    max_results: usize,
) -> Vec<GraphTraversalVisit> {
    visits
        .into_iter()
        .filter(|visit| visit.note_id != start_note_id)
        .take(max_results)
        .collect()
}

fn projection_diff(
    previous: Option<&GraphProjection>,
    current: &GraphProjection,
) -> GraphProjectionDiff {
    let previous = previous.cloned().unwrap_or_default();
    let previous_nodes = previous
        .nodes
        .iter()
        .map(|node| (node.note_id.as_str(), node))
        .collect::<BTreeMap<_, _>>();
    let current_nodes = current
        .nodes
        .iter()
        .map(|node| (node.note_id.as_str(), node))
        .collect::<BTreeMap<_, _>>();
    let previous_edges = previous
        .edges
        .iter()
        .map(|edge| (edge.edge_id.as_str(), edge))
        .collect::<BTreeMap<_, _>>();
    let current_edges = current
        .edges
        .iter()
        .map(|edge| (edge.edge_id.as_str(), edge))
        .collect::<BTreeMap<_, _>>();
    GraphProjectionDiff {
        added_node_ids: difference_keys(&current_nodes, &previous_nodes),
        removed_node_ids: difference_keys(&previous_nodes, &current_nodes),
        updated_node_ids: updated_node_ids(&previous_nodes, &current_nodes),
        added_edge_ids: difference_keys(&current_edges, &previous_edges),
        removed_edge_ids: difference_keys(&previous_edges, &current_edges),
        updated_edge_ids: updated_edge_ids(&previous_edges, &current_edges),
    }
}

fn difference_keys<T>(left: &BTreeMap<&str, T>, right: &BTreeMap<&str, T>) -> Vec<String> {
    left.keys()
        .filter(|key| !right.contains_key(**key))
        .map(|key| (*key).to_owned())
        .collect()
}

fn updated_node_ids(
    previous: &BTreeMap<&str, &GraphProjectionNode>,
    current: &BTreeMap<&str, &GraphProjectionNode>,
) -> Vec<String> {
    current
        .iter()
        .filter_map(|(note_id, current_node)| {
            previous
                .get(note_id)
                .filter(|previous_node| *previous_node != current_node)
                .map(|_| (*note_id).to_owned())
        })
        .collect()
}

fn updated_edge_ids(
    previous: &BTreeMap<&str, &GraphProjectionEdge>,
    current: &BTreeMap<&str, &GraphProjectionEdge>,
) -> Vec<String> {
    current
        .iter()
        .filter_map(|(edge_id, current_edge)| {
            previous
                .get(edge_id)
                .filter(|previous_edge| !edge_equal(previous_edge, current_edge))
                .map(|_| (*edge_id).to_owned())
        })
        .collect()
}

fn edge_equal(left: &GraphProjectionEdge, right: &GraphProjectionEdge) -> bool {
    left.edge_id == right.edge_id
        && left.source_note_id == right.source_note_id
        && left.source_path == right.source_path
        && left.target_note_id == right.target_note_id
        && left.target_path == right.target_path
        && left.relation == right.relation
        && left.confidence.to_bits() == right.confidence.to_bits()
        && left.source_kind == right.source_kind
}
