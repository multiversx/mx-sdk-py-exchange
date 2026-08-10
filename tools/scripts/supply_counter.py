import os
import sys

from tools.runners.common_runner import ExportedAccount, ExportedToken, read_accounts_from_json

# Re-exported so `ExportedToken` stays reachable here for readers of the token data below; the
# definitions themselves live in the runner support, which is the only copy.
__all__ = ["ExportedAccount", "ExportedToken", "SupplyCounter", "main", "read_accounts_from_json"]


class SupplyCounter:
    def __init__(self):
        # Dict structure: {token_name: {'supply': int, 'holders': set()}}
        self.token_data: dict[str, dict[str, int | set]] = {}

    def count_supplies(self, accounts: list[ExportedAccount]):
        for account in accounts:
            for token in account.account_tokens_supply:
                if token.token_name not in self.token_data:
                    self.token_data[token.token_name] = {
                        'supply': 0,
                        'holders': set()
                    }
                
                # Add the token supply (converting from string to int)
                self.token_data[token.token_name]['supply'] += int(token.supply)
                # Add holder address to set
                self.token_data[token.token_name]['holders'].add(account.address)

    def get_token_data(self) -> dict[str, dict[str, int | set]]:
        return self.token_data

    def get_summary(self) -> str:
        summary = []
        for token_name, data in self.token_data.items():
            summary.append(f"Token: {token_name}")
            summary.append(f"Total Supply: {data['supply']}")
            summary.append(f"Number of holders: {len(data['holders'])}")
            summary.append("---")
        return "\n".join(summary)


def main(args: list[str]):
    ###
    # Script takes in token account exports from shadowfork shards and computes
    #   the total supply of each token and the number of holders for each token.
    ###
    if len(args) == 0:
        print("Usage: python supply_counter.py <file1> <file2> ...")
        sys.exit(1)
    
    # Check if all files exist before processing
    for file in args:
        if not os.path.exists(file):
            print(f"Error: File '{file}' does not exist")
            sys.exit(1)
    
    supply_counter = SupplyCounter()
    for file in args:
        exported_accounts = read_accounts_from_json(file)
        supply_counter.count_supplies(exported_accounts)

    print(supply_counter.get_summary())


if __name__ == "__main__":
    main(sys.argv[1:])
