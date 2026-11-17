// Evaluated in the editor page by e2e_layout.py: measures what a reader sees in the SVG.
(() => {
  const S = window.vizeng, nodes = S.doc.nodes;
  const R = (n) => ({x0: n.x, y0: n.y, x1: n.x + n.w, y1: n.y + n.h});
  const inter = (a, b) => Math.max(0, Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0)) * Math.max(0, Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0));
  const inside = (p, r, m) => p.x > r.x0 + m && p.x < r.x1 - m && p.y > r.y0 + m && p.y < r.y1 - m;
  const edges = {}, labels = {};
  for (const g of document.querySelectorAll('#svg [data-edge]')) {
    const id = g.dataset.edge, e = S.doc.edges.find((x) => x.id === id);
    const path = [...g.querySelectorAll('path')].find((p) => p.getAttribute('pointer-events') === 'none');
    const L = path.getTotalLength(), pts = [];
    for (let s = 0; s <= L; s += 4) pts.push(path.getPointAtLength(s));
    edges[id] = {e, pts};
    const texts = [...g.querySelectorAll('text')];
    if (texts.length) {
      const bs = texts.map((t) => t.getBBox());
      labels[id] = {x0: Math.min(...bs.map((b) => b.x)), y0: Math.min(...bs.map((b) => b.y)),
                    x1: Math.max(...bs.map((b) => b.x + b.width)), y1: Math.max(...bs.map((b) => b.y + b.height))};
    }
  }
  const out = {labelOnNode: [], labelOnLabel: [], lineUnderLabel: [], edgeThroughNode: [], crossings: 0, labelWidths: []};
  for (const [id, lb] of Object.entries(labels)) {
    out.labelWidths.push(Math.round(lb.x1 - lb.x0));
    for (const nd of nodes) if (inter(lb, R(nd)) > 4) out.labelOnNode.push(`${id}/${nd.id}`);
    for (const [id2, lb2] of Object.entries(labels)) if (id < id2 && inter(lb, lb2) > 4) out.labelOnLabel.push(`${id}/${id2}`);
    for (const [id2, ed] of Object.entries(edges)) if (ed.pts.filter((p) => inside(p, lb, 1)).length >= 2) out.lineUnderLabel.push(`${id}/${id2}`);
  }
  for (const [id, ed] of Object.entries(edges))
    for (const nd of nodes) if (nd.id !== ed.e.from && nd.id !== ed.e.to && ed.pts.some((p) => inside(p, R(nd), 2))) out.edgeThroughNode.push(`${id}/${nd.id}`);
  const segX = (p, q, r, s) => { const d = (q.x - p.x) * (s.y - r.y) - (q.y - p.y) * (s.x - r.x); if (!d) return false;
    const t = ((r.x - p.x) * (s.y - r.y) - (r.y - p.y) * (s.x - r.x)) / d, u = ((r.x - p.x) * (q.y - p.y) - (r.y - p.y) * (q.x - p.x)) / d;
    return t > 0 && t < 1 && u > 0 && u < 1; };
  const ids = Object.keys(edges);
  for (let i = 0; i < ids.length; i++) for (let j = i + 1; j < ids.length; j++) {
    const A = edges[ids[i]], B = edges[ids[j]];
    if ([A.e.from, A.e.to].some((x) => x === B.e.from || x === B.e.to)) continue;  // shared endpoint: meeting is not crossing
    let hit = false;
    for (let a = 0; a + 1 < A.pts.length && !hit; a++) for (let b = 0; b + 1 < B.pts.length && !hit; b++) hit = segX(A.pts[a], A.pts[a + 1], B.pts[b], B.pts[b + 1]);
    if (hit) out.crossings++;
  }
  // co-location: mean distance between same-group node centers vs. all pairs
  const c = (n) => [n.x + n.w / 2, n.y + n.h / 2], dist = (a, b) => Math.hypot(c(a)[0] - c(b)[0], c(a)[1] - c(b)[1]);
  let same = [], all = [];
  const gn = nodes.filter((n) => n.group);
  for (let i = 0; i < gn.length; i++) for (let j = i + 1; j < gn.length; j++) { const d = dist(gn[i], gn[j]); all.push(d); if (gn[i].group === gn[j].group) same.push(d); }
  const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;
  out.groupTightness = +(mean(same) / mean(all)).toFixed(2);
  const t0 = performance.now(); for (let i = 0; i < 20; i++) window.vizengRoute(); out.renderMs = +((performance.now() - t0) / 20).toFixed(1);
  return out;
})
