import { ServiceName } from '@cryptodoge/api';
import { useIsServiceRunningQuery } from '@cryptodoge/api-react';
import FarmerStatus from '../constants/FarmerStatus';
import FullNodeState from '../constants/FullNodeState';
import useFullNodeState from './useFullNodeState';

export default function useFarmerStatus(): FarmerStatus {
  const fullNodeState = useFullNodeState();

  const { data: isRunning, isLoading: isLoadingIsRunning } = useIsServiceRunningQuery({
    service: ServiceName.FARMER,
  }, {
    pollingInterval: 1000,
  });

  const isLoading = isLoadingIsRunning;

  if (fullNodeState === FullNodeState.SYNCHING) {
    return FarmerStatus.SYNCHING;
  }

  if (fullNodeState === FullNodeState.ERROR) {
    return FarmerStatus.NOT_AVAILABLE;
  }

  if (isLoading /* || !farmerConnected */) {
    return FarmerStatus.NOT_CONNECTED;
  }

  if (!isRunning) {
    return FarmerStatus.NOT_RUNNING;
  }

  return FarmerStatus.FARMING;
}
