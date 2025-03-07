import React from 'react';
import styled from 'styled-components';
import { Trans } from '@lingui/macro';
import { List } from '@material-ui/core';
import {
  Wallet as WalletIcon,
  Farm as FarmIcon,
  Home as HomeIcon,
  Plot as PlotIcon,
  Pool as PoolIcon,
  Gamefi as GamefiIcon,
} from '@cryptodoge/icons';
import { Flex, SideBarItem } from '@cryptodoge/core';

const StyledRoot = styled(Flex)`
  height: 100%;
  overflow-y: auto;
`;

const StyledList = styled(List)`
  width: 100%;
`;

export default function DashboardSideBar() {
  return (
    <StyledRoot>
      <StyledList disablePadding>
        <SideBarItem
          to="/dashboard"
          icon={<HomeIcon fontSize="large" />}
          title={<Trans>Full Node</Trans>}
          end
        />
        <SideBarItem
          to="/dashboard/wallets"
          icon={<WalletIcon fontSize="large" />}
          title={<Trans>Wallets</Trans>}
        />
        <SideBarItem
          to="/dashboard/plot"
          icon={<PlotIcon fontSize="large" />}
          title={<Trans>Plots</Trans>}
        />
        <SideBarItem
          to="/dashboard/farm"
          icon={<FarmIcon fontSize="large" />}
          title={<Trans>Farm</Trans>}
        />
        <SideBarItem
          to="/dashboard/pool"
          icon={<PoolIcon fontSize="large" />}
          title={<Trans>Pool</Trans>}
        />
        <SideBarItem
          to="/dashboard/gamefi"
          icon={<GamefiIcon fontSize="large" />}
          title={<Trans>Gamefi</Trans>}
        />
      </StyledList>
    </StyledRoot>
  );
}
