
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

        done = self.print_connections(f=f, this=self)

        for s in self.sub:
            done += s.print_subgraph(f=f, nest=nest+1)

        print(pad, "}", file=f)
        return done

    def print_connections(self, f, this, done=[]):
        done = done[:]
        def get_payload(s):
            names = [ name for name, _ in s.layout ]
            return ",".join(names)
        for source, sink, s in Stream.connections:
            if this:
                if (source not in self.streams) or (sink not in self.streams):
                    continue
            if (source, sink) in done:
                continue
            done += [ (source, sink) ]
            p_in = get_payload(source)
            p_out = get_payload(sink)
            if p_in == p_out:
                if p_in == "data":
                    payload = ""
                else:
                    payload = p_in
            else:
                payload = p_in + " -> " + p_out
            ni, no = id(source), id(sink)
            print(f' {ni} -> {no} [label="{payload}"]', file=f)
        return done

    def print_dot(self, f):
        print("digraph D {", file=f)
        self.print_subgraph(f=f, nest=1)
        self.print_connections(f=f, this=None)
        print("}", file=f)

#
#

def get_clusters(m, nest=1, d=None):
    cluster = Cluster(m)

    names = d or {}
    names[id(m)] = True

    for name in dir(m):
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

#   FIN
