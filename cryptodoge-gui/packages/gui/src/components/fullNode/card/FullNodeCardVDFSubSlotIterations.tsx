import React from 'react';
import { Trans } from '@lingui/macro';
import { FormatLargeNumber, CardSimple } from '@cryptodoge/core';
import { useGetBlockchainStateQuery } from '@cryptodoge/api-react';

export default function FullNodeCardVDFSubSlotIterations() {
  const { data, isLoading, error } = useGetBlockchainStateQuery();
  const value = data?.peak?.subSlotIters ?? 0;

  return (
    <CardSimple
      loading={isLoading}
      valueColor="textPrimary"
      title={<Trans>VDF Sub Slot Iterations</Trans>}
      value={<FormatLargeNumber value={value} />}
      error={error}
    />
  );
}
