#include <stdexcept>

#include <ctype.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <sys/un.h>
#include <netdb.h>

class Transport {
public:
    virtual ~Transport() { }
    virtual int readfd() = 0;
    virtual int writefd() = 0;
};

class UnixTransport : public Transport
{
public:
    UnixTransport() :
        _readfd(-1),
        _writefd(-1)
    {
        int sv[2];
        if (socketpair(AF_UNIX, SOCK_STREAM, 0, sv) == -1) {
            throw std::runtime_error("");
        }
        _readfd = sv[0];
        _writefd = sv[1];
    }

    ~UnixTransport()
    {
        if (_readfd >= 0) {
            close(_readfd);
        }
        if (_writefd >= 0) {
            close(_writefd);
        }
    }

    int readfd()
    {
        return _readfd;
    }

    int writefd()
    {
        return _writefd;
    }

private:
    int _readfd;
    int _writefd;
};

class TcpTransport : public Transport
{
public:
    TcpTransport()
    {
        memset(&_addr, 0, sizeof(sockaddr_in));

        _sockfd = socket(AF_INET, SOCK_STREAM, 0);
        if (_sockfd < 0) {
            throw std::runtime_error("socket");
        }

        _addr.sin_family = AF_INET;
        _addr.sin_port = 0;
        _addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        if (bind(_sockfd, (struct sockaddr*)&_addr, sizeof(_addr)) < 0) {
            throw std::runtime_error("bind");
        }

        socklen_t len = sizeof(_addr);
        if (getsockname(_sockfd, (struct sockaddr*)&_addr, &len)) {
            throw std::runtime_error("getsockname");
        }

        if (listen(_sockfd, 1) == -1) {
            throw std::runtime_error("listen");
        }
    }

    ~TcpTransport()
    {
        if (_sockfd >= 0) {
            close(_sockfd);
        }
    }

    int readfd()
    {
        int readfd = socket(AF_INET, SOCK_STREAM, 0);
        if (readfd < 0) {
            throw std::runtime_error("socket");
        }

        if (connect(readfd, (struct sockaddr*)&_addr, sizeof(_addr)) == -1) {
            throw std::runtime_error("connect");
        }
        
        return readfd;
    }

    int writefd()
    {
        return accept(_sockfd, NULL, NULL);
    }

private:
    int _sockfd;
    struct sockaddr_in _addr;
};
