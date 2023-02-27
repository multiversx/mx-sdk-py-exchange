import sys
from typing import List

import graphene
import requests


def run_query(uri, query, statusCode, headers):
    request = requests.post(uri, json={'query': query}, headers=headers)
    if request.status_code == statusCode:
        return request.json()
    else:
        raise Exception(f"Unexpected status code returned: {request.status_code}")


def main(cli_args: List[str]):
    uri = 'https://graph.maiar.exchange/graphql'
    token = 'string'
    headers = {}
    status_code = 200

    query = """
    {
      stakingProxies{
        address
        dualYieldToken {
          name
        }
      }
    }
    """

    result = run_query(uri, query, status_code, headers)
    print(result)


if __name__ == "__main__":
    main(sys.argv[1:])