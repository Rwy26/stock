import sys, os
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
import graph_engine

g = graph_engine.build_graph(force=False)
nodes = g['nodes']
etfs = [(i, n) for i, n in enumerate(nodes) if n.get('isEtf')]
print('isEtf nodes:', len(etfs))
for i, n in etfs:
    es = [e for e in g['edges'] if e['a'] == i or e['b'] == i]
    mx = max((e['w'] for e in es), default=0)
    strong = [e for e in es if e['w'] >= 0.5]
    print(f"  {n['code']} edges={len(es)} maxW={mx} strong(>=0.5)={len(strong)}")
