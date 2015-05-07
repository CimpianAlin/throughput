#ifndef THREADED_DELETER_H
#define THREADED_DELETER_H

#include <deque>
#include <omnithread.h>

class threaded_deleter {
public:
    threaded_deleter() :
        _thread(0),
        _mutex(),
        _cond(&_mutex),
        _running(true)
    {
        _thread = new omni_thread(&threaded_deleter::thread_start, this);
        _thread->start();
    }

    ~threaded_deleter()
    {
        _mutex.lock();
        _running = false;
        _cond.signal();
        _mutex.unlock();
    }

    template <class T>
    void deallocate(T* data)
    {
        queue(new deleter<T>(data));
    }

    template <class T>
    void deallocate_array(T* data)
    {
        queue(new array_deleter<T>(data));
    }

private:
    struct deletable {
        virtual ~deletable() { }
    };

    template <class T>
    struct deleter : public deletable {
        deleter(T* p) :
            data(p)
        {
        }

        ~deleter()
        {
            delete data;
        }

        T* data;
    };

    template <class T>
    struct array_deleter : public deletable {
        array_deleter(T* p) :
            data(p)
        {
        }

        ~array_deleter()
        {
            delete[] data;
        }

        T* data;
    };

    void queue(deletable* item)
    {
        _mutex.lock();
        _queue.push_back(item);
        _cond.signal();
        _mutex.unlock();
    }

    void thread_run()
    {
        _mutex.lock();
        while (_running) {
            while (_queue.empty()) {
                _cond.wait();
                if (!_running) break;
            }
            delete _queue.front();
            _queue.pop_front();
        }
        _mutex.unlock();
    }

    static void thread_start(void* arg)
    {
        threaded_deleter* reader = (threaded_deleter*)arg;
        reader->thread_run();
    }

    omni_thread* _thread;
    omni_mutex _mutex;
    omni_condition _cond;
    volatile bool _running;
    std::deque<deletable*> _queue;
};

#endif // THREADED_DELETER_H
