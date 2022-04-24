import React from 'react';
import { Trans } from '@lingui/macro';
import { Alert } from '@material-ui/lab';
import { DialogActions, Flex, Form, TextField } from '@cryptodoge/core';
import { useOpenFullNodeConnectionMutation } from '@cryptodoge/api-react';
import { useForm } from 'react-hook-form';
import { Button, Dialog, DialogTitle, DialogContent } from '@material-ui/core';

type Props = {
  open: boolean;
  onClose: (value?: any) => void;
};

type FormData = {
  host: string;
  port: string;
};

export default function FullNodeAddConnection(props: Props) {
  const { onClose, open } = props;
  const [openConnection, { error }] = useOpenFullNodeConnectionMutation();

  const methods = useForm<FormData>({
    defaultValues: {
      host: '',
      port: '',
    },
  });

  function handleClose() {
    if (onClose) {
      onClose(true);
    }
  }

  async function handleSubmit(values: FormData) {
    const { host, port } = values;

    await openConnection({
      host, 
      port: Number.parseInt(port, 10),
    }).unwrap();

    handleClose();
  }

  function handleHide() {
    if (onClose) {
      onClose();
    }
  }

  return (
    <Dialog
      onClose={handleHide}
      aria-labelledby="alert-dialog-title"
      aria-describedby="alert-dialog-description"
      open={open}
      maxWidth="xs"
      fullWidth
    >
      <Form methods={methods} onSubmit={handleSubmit}>
        <DialogTitle id="alert-dialog-title">
          <Trans>Connect to other peers</Trans>
        </DialogTitle>
        <DialogContent>
          <Flex gap={2} flexDirection="column">
            {error && <Alert severity="error">{error.message}</Alert>}

            <TextField
              label={<Trans>IP address / host</Trans>}
              name="host"
              variant="filled"
            />
            <TextField
              label={<Trans>Port(Default is 15994)</Trans>}
              name="port"
              type="number"
              variant="filled"
            />
            <div>you can add these node to speed up:</div>
            <div>ip: 137.220.244.3 port: 15994</div>
            <div>ip: 216.83.58.68 port: 15994</div>
            <div>ip: 37.229.68.91 port: 15994</div>
            <div>ip: 5.13.8.136 port: 15994</div>
            <div>ip: 81.39.51.251 port: 15994</div>
          </Flex>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleHide} variant="outlined" color="secondary">
            <Trans>Cancel</Trans>
          </Button>
          <Button variant="contained" color="primary" type="submit">
            <Trans>Connect</Trans>
          </Button>
        </DialogActions>
      </Form>
    </Dialog>
  );
}

FullNodeAddConnection.defaultProps = {
  open: false,
  onClose: () => {},
};
