import React from 'react';
import { useRouteMatch, useHistory } from 'react-router-dom';
import { Trans } from '@lingui/macro';
import { Grid } from '@material-ui/core';
import { Restore as RestoreIcon, Add as AddIcon } from '@material-ui/icons';
import { Back, Flex } from '@cryptodoge/core';
import WalletCreateCard from '../create/WalletCreateCard';

export default function WalletCATSelect() {
  const history = useHistory();
  const { url } = useRouteMatch();

  function handleCreateNew() {
    history.push(`${url}/create`);
  }

  function handleCreateExisting() {
    history.push(`${url}/existing`);
  }

  return (
    <Flex flexDirection="column" gap={3}>
      <Flex flexGrow={1}>
        <Back variant="h5" to="/dashboard/wallets/create">
          <Trans>Cryptodoge Asset Token</Trans>
        </Back>
      </Flex>
      <Grid spacing={3} alignItems="stretch" container>
        <Grid xs={12} sm={6} md={4} item>
          <WalletCreateCard
            onSelect={handleCreateNew}
            title={<Trans>Create New Wallet</Trans>}
            icon={<AddIcon fontSize="large" color="primary" />}
          />
        </Grid>
        <Grid xs={12} sm={6} md={4} item>
          <WalletCreateCard
            onSelect={handleCreateExisting}
            title={<Trans>Recovery Wallet</Trans>}
            icon={<RestoreIcon fontSize="large" color="primary" />}
          />
        </Grid>
      </Grid>
    </Flex>
  );
}
