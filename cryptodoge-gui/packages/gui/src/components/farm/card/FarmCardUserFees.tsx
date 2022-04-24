import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useCurrencyCode, mojoToCryptodogeLocaleString, CardSimple } from '@cryptodoge/core';
import { useGetFarmedAmountQuery } from '@cryptodoge/api-react';

export default function FarmCardUserFees() {
  const currencyCode = useCurrencyCode();
  const { data, isLoading, error } = useGetFarmedAmountQuery();

  const feeAmount = data?.feeAmount;

  const userTransactionFees = useMemo(() => {
    if (feeAmount !== undefined) {
      return (
        <>
          {mojoToCryptodogeLocaleString(feeAmount)}
          &nbsp;
          {currencyCode}
        </>
      );
    }
  }, [feeAmount]);

  return (
    <CardSimple
      title={<Trans>User Transaction Fees</Trans>}
      value={userTransactionFees}
      loading={isLoading}
      error={error}
    />
  );
}
