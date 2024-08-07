
from amaranth import *
from .stream import Stream

#
#

class Cluster:

    @staticmethod
    def get_name(obj):
        if hasattr(obj, "name"):
            return obj.name
        return obj.__class__.__name__
 
    def __init__(self, obj):
        self.obj = obj
        self.sub = []
        self.streams = []

    def add(self, obj):
        self.sub.append(obj)

    def add_stream(self, obj):
        self.streams.append(obj)

    def print_node(self, f, nest, node, style="filled", name=None):
        pad = " " * nest
        n = id(node)
        label = name or self.get_name(node)
        print(pad, f'{n} [shape=box,style={style},label="{label}"]', file=f)

    def print_subgraph(self, f, nest=0):
        pad = " " * nest
        n = id(self)
        print(pad, f"Subgraph cluster_{n}_x", "{", file=f)
        print(pad, f"color=blue;", file=f)
        print(pad, f"style=rounded;", file=f)
        name = self.get_name(self.obj)
        print(pad, f'label = "{name}";', file=f)
        for node in self.streams:
            self.print_node(f, nest, node)

        if not self.streams:
            # print a dummy node
            self.print_node(f=f, nest=nest, node=self, style="rounded", name=" ")

        for s in self.sub:
            s.print_subgraph(f=f, nest=nest+1)

        print(pad, "}", file=f)

    def print_connections(self, f, this):
        def get_payload(s, exclude):
            if hasattr(s, "get_layout"):
                names = []
                for name, _ in s.get_layout():
                    if name in exclude:
                        continue
                    if fn and (name in fn):
                        name = f"{fn[name].__name__}({name})"
                    names.append(name)
                if not names:
                    return "[]"
                return ",".join(names)
            return "xxx"
        for source, sink, s, exclude, fn in Stream.connections:
            if this:
                if (source not in self.streams) or (sink not in self.streams):
                    continue
            p_in = get_payload(source, exclude)
            p_out = get_payload(sink, exclude)
            if p_in == p_out:
                if p_in == "data":
                    payload = ""
                else:
                    payload = p_in
            else:
                payload = p_in + " -> " + p_out
            ni, no = id(source), id(sink)
            if s:
                style = "[arrowhead=empty,penwidth=1]"
            else:
                style = ""
            print(f' {ni} -> {no} [label="{payload}"]{style}', file=f)

    def print_dot(self, f):
        print("digraph D {", file=f)
        self.print_subgraph(f=f, nest=1)
        self.print_connections(f=f, this=None)
        print("}", file=f)

#
#

def get_clusters(m, nest=1, d=None):
    cluster = Cluster(m)
    if hasattr(m, "dot_dont_expand"):
        return cluster

    names = d or {}
    names[id(m)] = True

    for name in dir(m):
        if name == "next":
            continue
        a = getattr(m, name)
        if id(a) in names:
            continue
        if isinstance(a, Elaboratable):
            c = get_clusters(a, nest + 1, names)
            cluster.add(c)
        if isinstance(a, Stream):
            cluster.add_stream(a)

    return cluster

def run(dot, png):
    import subprocess
    cmd = f"dot -T png {dot} -o {png}"
    print("run", cmd)
    subprocess.call(cmd, shell=True)
    print("generated", png)

def graph(m, d_path, p_path):
    f = open(d_path, "w")
    c = get_clusters(m)
    c.print_dot(f)
    f.close()
    run(d_path, p_path)

#   FIN
