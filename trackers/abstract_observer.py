from abc import ABC, abstractmethod


class Subscriber(ABC):
    @abstractmethod
    def update(self, publisher: "Publisher"):
        pass


class Publisher(ABC):
    @abstractmethod
    def subscribe(self, subscriber: Subscriber):
        pass

    @abstractmethod
    def unsubscribe(self, subscriber: Subscriber):
        pass

    @abstractmethod
    def notify(self):
        pass
