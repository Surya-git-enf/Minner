# decoder.py
from web3 import Web3
from eth_abi import decode_abi
# We'll use minimal signature matching for common router functions

# Common swap function signatures (first 4 bytes)
SIG_SWAP_EXACT_ETH_FOR_TOKENS = Web3.keccak(text="swapExactETHForTokensSupportingFeeOnTransferTokens(uint256,address[],address,uint256)")[:4].hex()
SIG_SWAP_EXACT_TOKENS_FOR_ETH = Web3.keccak(text="swapExactTokensForETHSupportingFeeOnTransferTokens(uint256,uint256,address[],address,uint256)")[:4].hex()
SIG_SWAP_EXACT_TOKENS_FOR_TOKENS = Web3.keccak(text="swapExactTokensForTokensSupportingFeeOnTransferTokens(uint256,uint256,address[],address,uint256)")[:4].hex()

def decode_swap_input(input_data_hex):
    if not input_data_hex or input_data_hex == "0x":
        return None
    data = input_data_hex if input_data_hex.startswith("0x") else "0x"+input_data_hex
    sig = data[2:10]
    # Note: robust decoding uses ABI; here we return descriptive info
    if sig == SIG_SWAP_EXACT_ETH_FOR_TOKENS[2:]:
        return {"type":"swapExactETHForTokens", "raw": data}
    if sig == SIG_SWAP_EXACT_TOKENS_FOR_ETH[2:]:
        return {"type":"swapExactTokensForETH", "raw": data}
    if sig == SIG_SWAP_EXACT_TOKENS_FOR_TOKENS[2:]:
        return {"type":"swapExactTokensForTokens", "raw": data}
    return {"type":"unknown", "raw": data}
