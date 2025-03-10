import React from 'react';
import { Trans } from '@lingui/macro';
import { ConfirmDialog, More, useOpenDialog } from '@cryptodoge/core';
import {
  Box,
  Divider,
  ListItemIcon,
  MenuItem,
  Typography,
} from '@material-ui/core';
import {
  DeleteForever as DeleteForeverIcon,
  Info as InfoIcon,
} from '@material-ui/icons';
import { useStopPlottingMutation } from '@cryptodoge/api-react';
import type PlotQueueItem from '../../../types/PlotQueueItem';
import PlotStatus from '../../../constants/PlotStatus';
import PlotQueueLogDialog from './PlotQueueLogDialog';

type Props = {
  queueItem: PlotQueueItem;
};

export default function PlotQueueAction(props: Props) {
  const {
    queueItem: { id, state },
  } = props;

  const [stopPlotting] = useStopPlottingMutation();
  const openDialog = useOpenDialog();
  const canDelete = state !== PlotStatus.REMOVING;

  async function handleDeletePlot() {
    if (!canDelete) {
      return;
    }

    await openDialog(
      <ConfirmDialog
        title={<Trans>Delete Plot</Trans>}
        confirmTitle={<Trans>Delete</Trans>}
        confirmColor="danger"
        onConfirm={() => stopPlotting({
          id,
        }).unwrap()}
      >
        <Trans>
          Are you sure you want to delete the plot? The plot cannot be
          recovered.
        </Trans>
      </ConfirmDialog>,
    );
  }

  function handleViewLog() {
    openDialog(<PlotQueueLogDialog id={id} />);
  }

  return (
    <More>
      {({ onClose }) => (
        <Box>
          {state === PlotStatus.RUNNING && (
            <>
              <MenuItem
                onClick={() => {
                  onClose();
                  handleViewLog();
                }}
              >
                <ListItemIcon>
                  <InfoIcon fontSize="small" />
                </ListItemIcon>
                <Typography variant="inherit" noWrap>
                  <Trans>View Log</Trans>
                </Typography>
              </MenuItem>
              <Divider />
            </>
          )}

          <MenuItem
            onClick={() => {
              onClose();
              handleDeletePlot();
            }}
            disabled={!canDelete}
          >
            <ListItemIcon>
              <DeleteForeverIcon fontSize="small" />
            </ListItemIcon>
            <Typography variant="inherit" noWrap>
              <Trans>Delete</Trans>
            </Typography>
          </MenuItem>
        </Box>
      )}
    </More>
  );
}
