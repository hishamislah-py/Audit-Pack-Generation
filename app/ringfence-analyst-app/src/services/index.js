/* Choose the data service: 'http' = the Ringfence backend (httpService.js), 'mock' = in-browser mock (mockService.js). */
import { createHttpService } from './httpService.js';
import { createMockService } from './mockService.js';

export function createDataService(kind, config) {
  return kind === 'http' ? createHttpService(config) : createMockService(config);
}
