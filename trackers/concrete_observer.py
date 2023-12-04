from typing import List, Any
from trackers.abstract_observer import Publisher, Subscriber
from utils.utils_chain import Account
from contracts.contract_identities import DEXContractInterface


class Observable(Publisher):
    observers: List[Subscriber] = []
    contract: DEXContractInterface
    user: Account
    event: Any
    tx_hash: str

    def subscribe(self, subscriber: Subscriber):
        print('A new observer has subscribed')
        self.observers.append(subscriber)

    def unsubscribe(self, subscriber: Subscriber):
        print('A observer has unsubscribed')
        self.observers.remove(subscriber)

    def notify(self):
        for observer in self.observers:
            observer.update(self)

    def set_event(self, contract: DEXContractInterface, user: Account, event_data: Any, txhash: str):
        self.contract = contract
        self.user = user
        self.event = event_data
        self.tx_hash = txhash
        self.notify()


class Observer(Subscriber):
    def update(self, publisher: Observable):
        pass
