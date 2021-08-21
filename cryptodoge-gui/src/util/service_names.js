export const service_wallet = 'cryptodoge_wallet';
export const service_full_node = 'cryptodoge_full_node';
export const service_farmer = 'cryptodoge_farmer';
export const service_harvester = 'cryptodoge_harvester';
export const service_simulator = 'cryptodoge_full_node_simulator';
export const service_daemon = 'daemon';
export const service_plotter = 'cryptodoge plots create';

// Corresponds with outbound_message.py NodeTypes
export const service_connection_types = {
  1: 'Full Node',
  2: 'Harvester',
  3: 'Farmer',
  4: 'Timelord',
  5: 'Introducer',
  6: 'Wallet',
  7: 'Plotter',
};
