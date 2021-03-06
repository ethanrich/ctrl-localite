from pytest import fixture
from localite.flow.mrk import MRK, Buffer, Receiver, expectation
from localite.flow.payload import Queue, Payload
import time
import pylsl
import threading


def test_buffer():
    b = Buffer()
    inp = [1, 2, 3, 4, 5]
    for i in inp:
        b.put(i)
    out = b.get_as_list()
    assert inp == out


def test_receiver():
    outlet = pylsl.StreamOutlet(
        pylsl.StreamInfo(
            name="test_marker",
            type="Marker",
            channel_count=1,
            nominal_srate=0,
            channel_format="string",
            source_id="test_marker_" + pylsl.library_info(),
        )
    )
    r = Receiver(name="test_marker")
    r.start()
    time.sleep(5)

    # buffer should contain everything which was sent
    inp = ["1", "2", "3", "4", "5"]
    for i in inp:
        outlet.push_sample([i])
    time.sleep(0.1)
    out = [i[0][0] for i in r.buffer.get_as_list()]
    assert inp == out

    # buffer should be empty now
    out = [i[0][0] for i in r.buffer.get_as_list()]
    assert out == []

    # buffer should be cleared upon call
    inp = ["1", "2", "3", "4", "5"]
    for i in inp:
        outlet.push_sample([i])
    time.sleep(0.1)
    r.clear()
    out = [i[0][0] for i in r.buffer.get_as_list()]
    assert out == []
    # receiver should stop within 5 seconds
    r.stop()
    t0 = time.time()
    while r.is_running.is_set() and time.time() - t0 < 5:
        pass
    assert not r.is_running.is_set()


@fixture
def mrk(capsys):
    mrk = Queue()
    mrk = MRK(mrk)
    mrk.start()
    mrk.await_running()
    pipe = capsys.readouterr()
    assert "localite_marker" in pipe.out
    yield mrk
    killpayload = Payload("cmd", "poison-pill", 12345)
    mrk.queue.put(killpayload)
    time.sleep(0.5)
    pipe = capsys.readouterr()
    assert "Shutting MRK down" in pipe.out


def test_latency_below_1ms(mrk, capsys):
    pl = Payload("mrk", "test_latency", pylsl.local_clock())
    mrk.queue.put(pl)
    time.sleep(0.01)
    pipe = capsys.readouterr()
    latency = pipe.out.split("delayed by ")[1].split("ms")[0]
    assert float(latency) < 0.001


def test_expectation():
    assert expectation('{"get": "coil_0_amplitude"}') == "coil_0_amplitude"
    assert expectation('{"single_pulse": "COIL_0"}') == "coil_0_didt"
    assert expectation('{"coil_0_amplitude": 1}') == "coil_0_amplitude"


def test_sending_out(mrk):
    from os import environ

    if (
        "GITHUB_ACTION" in environ.keys()
    ):  # the LSL sending seems to deadlock on their server
        return

    class Listener(threading.Thread):
        def __init__(self):
            threading.Thread.__init__(self)
            self.running = False

        def run(self):
            sinfo = pylsl.resolve_byprop("name", "localite_marker")[0]
            stream = pylsl.StreamInlet(sinfo)
            msg = []
            time.sleep(1)
            msg, t1 = stream.pull_chunk()
            self.running = True
            while self.running:
                try:
                    msg, t1 = stream.pull_chunk()
                    print(msg)
                    if msg == []:
                        time.sleep(0.001)
                    else:
                        self.running = False
                except pylsl.pylsl.LostError:
                    break
            self.msg = msg
            self.t1 = t1
            del stream

    l = Listener()
    l.start()
    while not l.running:
        pass
    t0 = pylsl.local_clock()
    pl = Payload("mrk", '{"test":"sending_out"}', t0)
    mrk.queue.put(pl)
    while l.running:
        pass
    assert abs(l.t1[0] - t0) < 0.001
    assert l.msg[0][0] == pl.msg
    l.running = False
