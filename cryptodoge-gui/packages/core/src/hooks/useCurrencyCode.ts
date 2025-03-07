import { useGetNetworkInfoQuery } from '@cryptodoge/api-react';

export default function useCurrencyCode(): string | undefined {
  const { data: networkInfo, isLoading } = useGetNetworkInfoQuery();

  if (isLoading || !networkInfo) {
    return undefined;
  }

  return networkInfo.networkPrefix.toUpperCase();
}
