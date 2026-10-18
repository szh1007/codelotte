import threading

counter = 0


def increment():
    global counter
    value = counter
    value += 1
    counter = value


def run(threads):
    workers = [threading.Thread(target=increment) for _ in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    return counter


if __name__ == "__main__":
    print(run(8))
