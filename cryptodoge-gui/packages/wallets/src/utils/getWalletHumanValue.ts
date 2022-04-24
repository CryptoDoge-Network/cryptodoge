import type { Wallet } from '@cryptodoge/api';
import { WalletType } from '@cryptodoge/api';
import { mojoToCATLocaleString, mojoToCryptodogeLocaleString } from '@cryptodoge/core';

export default function getWalletHumanValue(wallet: Wallet, value: number): string {
  return wallet.type === WalletType.CAT
    ? mojoToCATLocaleString(value)
    : mojoToCryptodogeLocaleString(value);
}
