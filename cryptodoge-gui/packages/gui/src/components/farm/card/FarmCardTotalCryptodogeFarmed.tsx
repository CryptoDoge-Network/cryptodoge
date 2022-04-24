import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useCurrencyCode, mojoToCryptodogeLocaleString, CardSimple } from '@cryptodoge/core';
import { useGetFarmedAmountQuery } from '@cryptodoge/api-react';

export default function FarmCardTotalCryptodogeFarmed() {
  const currencyCode = useCurrencyCode();
  const { data, isLoading, error } = useGetFarmedAmountQuery();

  const farmedAmount = data?.farmedAmount;

  const totalCryptodogeFarmed = useMemo(() => {
    if (farmedAmount !== undefined) {
      return (
        <>
          {mojoToCryptodogeLocaleString(farmedAmount)}
          &nbsp;
          {currencyCode}
        </>
      );
    }
  }, [farmedAmount]);

  return (
    <CardSimple
      title={<Trans>Total Cryptodoge Farmed</Trans>}
      value={totalCryptodogeFarmed}
      loading={isLoading}
      error={error}
    />
  );
}
