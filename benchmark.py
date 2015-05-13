import sys
import time
import getopt
import math
import numpy
import itertools

import numa
from procinfo import CpuInfo, ProcessInfo

import raw
import corba
import rhbulkio as bulkio

def samples_to_int(value):
    scale = 1
    if value[-1].isalpha():
        suffix = value[-1].lower()
        value = value[:-1]
        if suffix == 'k':
            scale = 1024
        elif suffix == 'm':
            scale = 1024**2
    return int(value)*scale

def time_to_sec(value):
    scale = 1.0
    if value[-1].isalpha():
        suffix = value[-1].lower()
        value = value[:-1]
        if suffix == 'm':
            scale = 60.0
        elif suffix == 's':
            scale = 1.0
    return float(value)*scale

def to_gbps(value):
    return '%.2f' % (value/(1024**3))

def to_percent(value):
    return '%.1f' % (value*100.0)

def to_binary(value):
    suffixes = [ '', 'KB', 'MB', 'GB' ]
    index = int(math.floor(math.log(value, 1024)))
    return '%d%s' % (value/math.pow(1024, index), suffixes[index])

class AggregateTest(object):
    def __init__(self, factory, data_format, transfer_size, numa_policy, count):
        self.tests = [factory.create(data_format, transfer_size, numa_policy.next()) for ii in xrange(count)]
        self.reader_stats = [ProcessInfo(t.get_reader()) for t in self.tests]
        self.writer_stats = [ProcessInfo(t.get_writer()) for t in self.tests]

    def start(self):
        for test in self.tests:
            test.start()

    def stop(self):
        for test in self.tests:
            test.stop()

    def get_reader_stats(self):
        return [s.poll() for s in self.reader_stats]

    def get_writer_stats(self):
        return [s.poll() for s in self.writer_stats]

    def received(self):
        return sum(test.received for test in self.tests)

    def transfer_size(self, length):
        for test in self.tests:
            test.transfer_size(length)

    def terminate(self):
        for test in self.tests:
            test.terminate()


class Statistics(object):

    class Listener(object):
        def __init__(self, stats):
            self.stats = stats
            stats.add_listener(self)

        def add_sample(self, **sample):
            pass

    def __init__(self):
        self.samples = []
        self.listeners = []

    def add_listener(self, listener):
        self.listeners.append(listener)

    def add_sample(self, sample):
        self.samples.append(sample)

        for listener in self.listeners:
            listener.add_sample(**sample)

    def get_max_sample(self, field):
        return max(self.samples, key=lambda s:s[field])

    def get_max_value(self, field):
        return self.get_max_sample(field)[field]

    def get_field(self, field):
        return [s[field] for s in self.samples]

    def get_groups(self, field):
        return [list(g) for k, g in itertools.groupby(self.samples, lambda s:s[field])]


class Averager(Statistics.Listener):
    def __init__(self, stats, window_size):
        Statistics.Listener.__init__(self, stats)
        self.values = []
        self.window_size = window_size
        self.max_window_size = 2 * self.window_size

    def add_sample(self, rate, **kw):
        self.values.append(rate)

    def reset(self):
        self.values = []

    def is_stable(self, tolerance):
        if len(self.values) < self.window_size:
            return False
        elif len(self.values) >= self.max_window_size:
            return True

        return self.variance() <= tolerance

    def get_data(self):
        return self.values

    def average(self):
        return numpy.average(self.get_data())

    def variance(self):
        data = self.get_data()
        return numpy.std(data)/numpy.average(data)

    def length(self):
        return len(self.values)


class ProgressMonitor(object):
    def test_started(self, size):
        sys.stdout.write(to_binary(size))
        sys.stdout.flush()

    def add_sample(self, **kw):
        sys.stdout.write('.')
        sys.stdout.flush()

    def test_complete(self):
        sys.stdout.write('\n')


class TextSeries(object):
    def __init__(self, name):
        self.name = name

    def test_complete(self, stats, average):
        best = average.get_max_sample('rate')
        print 'Average:', to_binary(best['size']), to_gbps(best['rate'])
        peak = stats.get_max_sample('rate')
        print 'Peak:   ', to_binary(peak['size']), to_gbps(peak['rate'])

    def add_sample(self, **kw):
        pass


class TextDisplay(object):
    def add_series(self, name):
        return TextSeries(name)

    def update(self):
        pass

    def wait(self):
        pass


class BarSeries(object):
    def __init__(self, graph, offset, color):
        self.graph = graph
        self.offset = offset
        self.color = color

    def add_sample(self, size, rate, dev, **kw):
        self.graph.draw_bar(size, rate, dev, self.offset, self.color)

    def test_complete(self, stats, average):
        pass


class BarGraph(object):
    def __init__(self, bins):
        from matplotlib import pyplot
        globals()['pyplot'] = pyplot

        self.figure = pyplot.figure()
        self.figure.canvas.set_window_title('REDHAWK Benchmark')

        # Create a bar graph of average throughput vs. transfer size
        self.bar_plot = self.figure.add_subplot(111)
        self.bar_plot.set_xlabel('Transfer size')
        self.bar_plot.set_ylabel('Throughput (Bps)')

        self.width = 1.0/3.0
        self.offset = 0.0
        self.colors = itertools.cycle('bgrcmyk')

        self.bins = dict((bin, index) for index, bin in enumerate(bins))
        self.bar_plot.set_xticks(numpy.arange(len(self.bins))+0.5)
        self.bar_plot.set_xticklabels([to_binary(b) for b in bins])
        self.bar_plot.set_xbound(0.0, len(self.bins))

        self.figure.show()

    def add_series(self, name):
        offset = self.offset
        self.offset += self.width
        return BarSeries(self, offset, self.colors.next())

    def wait(self):
        pyplot.show()

    def update(self):
        self.figure.canvas.flush_events()

    def draw_bar(self, bin, value, dev, offset, color):
        pos = self.bins[bin] + offset
        self.bar_plot.bar([pos], [value], color=color, width=self.width, yerr=dev, ecolor='black')
        self.bar_plot.set_xbound(0.0, len(self.bins))
        self.figure.canvas.draw()


class TransferSizeTest(object):
    def __init__(self, sizes, poll_time, window_size, tolerance):
        self.sizes = sizes
        self.poll_time = poll_time
        self.window_size = window_size
        self.tolerance = tolerance
        self.__idle_tasks = []

    def add_idle_task(self, task):
        self.__idle_tasks.append(task)

    def run(self, test, monitor, avg_monitor):
        stats = Statistics()
        window = Averager(stats, self.window_size)

        if monitor:
            stats.add_listener(monitor)

        average = Statistics()

        if avg_monitor:
            average.add_listener(avg_monitor)

        reader_stats = ProcessInfo(test.get_reader())
        writer_stats = ProcessInfo(test.get_writer())

        num_cpus = sum(len(numa.get_cpus(n)) for n in numa.get_nodes())
        cpu_info = CpuInfo()

        test.start()

        start = time.time()
        next = start + self.poll_time

        now = start
        last_time = start
        last_total = 0

        for transfer_size in self.sizes:
            monitor.test_started(transfer_size)

            test.transfer_size(transfer_size)
            window.reset()

            # Wait until window is stable (or it's taken long enough that we can
            # assume it will never stabilize) to make decisions
            while not window.is_stable(self.tolerance):
                # Allow UI to update, etc.
                self.idle_tasks()

                # Wait until next scheduled poll time
                sleep_time = next - time.time()
                next += self.poll_time
                if sleep_time > 0.0:
                    time.sleep(sleep_time)

                # Measure time elapsed since last sample
                now = time.time()
                elapsed = now - last_time
                last_time = now

                # Calculate average throughput over the sample period
                current_total = test.received
                delta = current_total - last_total
                last_total = current_total
                current_rate = delta / elapsed

                # Aggregate CPU usage
                reader = reader_stats.poll()
                writer = writer_stats.poll()

                system = cpu_info.poll()
                sys_cpu = num_cpus * 100.0 / sum(system.values())

                sample = {'time': now-start,
                          'rate': current_rate,
                          'size': transfer_size,
                          'write_cpu': writer['cpu'] * sys_cpu,
                          'write_rss': writer['rss'],
                          'write_majflt': writer['majflt'],
                          'write_minflt': writer['minflt'],
                          'write_threads': writer['threads'],
                          'read_cpu': reader['cpu'] * sys_cpu,
                          'read_rss': reader['rss'],
                          'read_majflt': reader['majflt'],
                          'read_minflt': reader['minflt'],
                          'read_threads': reader['threads'],
                          'cpu_user': system['user'] * sys_cpu,
                          'cpu_system': system['system'] * sys_cpu,
                          'cpu_idle': system['idle'] * sys_cpu,
                          'cpu_iowait': system['iowait'] * sys_cpu,
                          'cpu_irq': system['irq'] * sys_cpu,
                          'cpu_softirq': system['softirq'] * sys_cpu,
                          }
                stats.add_sample(sample)

            # Add the windowed average throughput to the stats
            current_average = window.average()
            # NB: Account for the fact that the variance is normalized
            current_dev = window.variance()*current_average
            sample = {'rate': current_average,
                      'size': transfer_size,
                      'dev':  current_dev}
            average.add_sample(sample)

            monitor.test_complete()

        test.stop()

        if avg_monitor:
            avg_monitor.test_complete(stats, average)

        return stats, average

    def idle_tasks(self):
        for task in self.__idle_tasks:
            task()


if __name__ == '__main__':
    transport = 'unix'
    numa_distance = None
    poll_time = 0.25
    window_size = 5
    tolerance = 0.1
    nogui = False

    opts, args = getopt.getopt(sys.argv[1:], 'w:t:d:', ['transport=', 'numa-distance=', 'no-gui'])
    for key, value in opts:
        if key == '-w':
            window_size = int(value)
        elif key == '-t':
            poll_time = float(value)
        elif key == '-d':
            tolerance = float(value)
        elif key == '--transport':
            transport = value
        elif key == '--numa-distance':
            numa_distance = int(value)
        elif key == '--no-gui':
            nogui = True

    csv_fields = [
        ('time', 'time(s)'),
        ('rate', 'rate(Bps)'),
        ('size', 'transfer size(B)'),
        ('write_cpu', 'writer cpu(%)'),
        ('write_rss', 'writer rss'),
        ('write_majflt', 'writer major faults'),
        ('write_minflt', 'writer minor faults'),
        ('write_threads', 'writer threads'),
        ('read_cpu', 'reader cpu(%)'),
        ('read_rss', 'reader rss'),
        ('read_majflt', 'reader major faults'),
        ('read_minflt', 'reader minor faults'),
        ('read_threads', 'reader threads'),
        ('cpu_user', 'user CPU(%)'),
        ('cpu_system', 'system CPU(%)'),
        ('cpu_idle', 'idle CPU(%)'),
        ('cpu_iowait', 'I/O wait CPU(%)'),
        ('cpu_irq', 'IRQ CPU(%)'),
        ('cpu_softirq', 'soft IRQ CPU(%)'),
    ]

    # Try powers of two from 16K to 32M
    transfer_sizes = [2**x for x in xrange(14, 26)]
    if nogui:
        display = TextDisplay()
    else:
        display = BarGraph(transfer_sizes)

    test = TransferSizeTest(transfer_sizes, poll_time, window_size, tolerance)
    test.add_idle_task(display.update)

    for interface in ('Raw', 'CORBA', 'BulkIO'):
        if interface == 'Raw':
            factory = raw.factory(transport)
        elif interface == 'CORBA':
            factory = corba.factory(transport)
        elif interface == 'BulkIO':
            factory = bulkio.factory(transport)
        print 'Measuring', interface

        numa_policy = numa.NumaPolicy(numa_distance)

        stream = factory.create('octet', numa_policy.next())
        try:
            stats, average = test.run(stream, ProgressMonitor(), display.add_series(interface))
        finally:
            stream.terminate()

        filename = interface.lower()+'.csv'
        with open(filename, 'w') as f:
            print >>f, ','.join(title for name, title in csv_fields)
            for s in stats.samples:
                print >>f, ','.join(str(s[name]) for name, title in csv_fields)

    display.wait()
