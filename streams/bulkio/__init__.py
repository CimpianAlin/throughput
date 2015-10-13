#
# This file is protected by Copyright. Please refer to the COPYRIGHT file
# distributed with this source distribution.
#
# This file is part of REDHAWK throughput.
#
# REDHAWK throughput is free software: you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# REDHAWK throughput is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see http://www.gnu.org/licenses/.
#
import os

__all__ = ('factory')

PATH = os.path.dirname(__file__)

class NumaLauncher(object):
    def __init__(self, policy):
        self.policy = policy

    def isInteractive(self):
        return False

    def modifiesCommand(self):
        return True

    def canAttach(self):
        return False

    def wrap(self, command, arguments):
        command = self.policy([command] + arguments)
        return command[0], command[1:]


class BulkioStream(object):
    def __init__(self, format, numa_policy):
        launcher = NumaLauncher(numa_policy)
        self.writer = sb.launch(os.path.join(PATH, 'writer/writer.spd.xml'), debugger=launcher)
        self.reader = sb.launch(os.path.join(PATH, 'reader/reader.spd.xml'), debugger=launcher)
        self.writer.connect(self.reader)

    def start(self):
        sb.start()

    def stop(self):
        sb.stop()

    def get_reader(self):
        return self.reader._process.pid()

    def get_writer(self):
        return self.writer._process.pid()

    def transfer_size(self, size):
        self.writer.transfer_length = size

    def received(self):
        return int(self.reader.received)

    def terminate(self):
        self.writer.releaseObject()
        self.reader.releaseObject()

class BulkioStreamFactory(object):
    def __init__(self, transport):
        configfile = 'config/omniORB-%s.cfg' % transport
        os.environ['OMNIORB_CONFIG'] = os.path.join(PATH, configfile)
        from ossie.utils import sb
        globals()['sb'] = sb

    def create(self, format, numa_policy):
        return BulkioStream(format, numa_policy)

    def cleanup(self):
        pass

def factory(transport):
    return BulkioStreamFactory(transport)
