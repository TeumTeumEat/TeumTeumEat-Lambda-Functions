import { S3Client, GetObjectCommand } from '@aws-sdk/client-s3';
import sharp from 'sharp';

// Lambda@Edge does not support environment variables, so limits live here
const MAX_DIMENSION = 4096;
const DEFAULT_QUALITY = 80;
const FORMATS = new Set(['jpeg', 'png', 'webp', 'avif']);
const FORMAT_ALIASES = { jpg: 'jpeg' };
// Generated responses are capped at 1MB including headers
const MAX_BODY_BYTES = 1000 * 1000;

const s3Clients = new Map();

export const handler = async (event) => {
  const { request, response } = event.Records[0].cf;

  if (response.status !== '200') return response;

  const params = parseParams(request.querystring);
  if (!params) return response;

  const origin = request.origin?.s3;
  const location = origin && parseS3Domain(origin.domainName);
  if (!location) return response;

  const key = decodeURIComponent(`${origin.path ?? ''}${request.uri}`).slice(1);

  try {
    const object = await getS3Client(location.region).send(
      new GetObjectCommand({ Bucket: location.bucket, Key: key }),
    );
    const source = Buffer.from(await object.Body.transformToByteArray());
    const result = await resize(source, params);

    if (!result) return response;

    const body = result.data.toString('base64');
    if (body.length > MAX_BODY_BYTES) {
      console.warn(`Resized image too large to return (${body.length} bytes): ${key}`);
      return response;
    }

    response.body = body;
    response.bodyEncoding = 'base64';
    response.headers['content-type'] = [{ key: 'Content-Type', value: `image/${result.format}` }];
    delete response.headers['content-length'];
    return response;
  } catch (error) {
    console.error(`Failed to resize ${location.bucket}/${key}`, error);
    return response;
  }
};

// Returns null when no params are given or any param is invalid, so the original is served
export function parseParams(querystring) {
  const query = new URLSearchParams(querystring);
  const w = query.get('w');
  const h = query.get('h');
  const f = query.get('f');
  const q = query.get('q');

  if (w === null && h === null && f === null && q === null) return null;

  const width = w === null ? undefined : toInt(w, MAX_DIMENSION);
  const height = h === null ? undefined : toInt(h, MAX_DIMENSION);
  const quality = q === null ? DEFAULT_QUALITY : toInt(q, 100);
  const format = f === null ? undefined : (FORMAT_ALIASES[f] ?? f);

  if (Number.isNaN(width) || Number.isNaN(height) || Number.isNaN(quality)) return null;
  if (format !== undefined && !FORMATS.has(format)) return null;

  return { width, height, format, quality };
}

export async function resize(source, { width, height, format, quality }) {
  const image = sharp(source).rotate(); // apply EXIF orientation before resizing
  const outputFormat = format ?? (await image.metadata()).format;

  // Keep the original for formats we don't encode (gif, svg, ...)
  if (!FORMATS.has(outputFormat)) return null;

  if (width || height) {
    image.resize({ width, height, fit: 'inside', withoutEnlargement: true });
  }

  const data = await image.toFormat(outputFormat, { quality }).toBuffer();
  return { data, format: outputFormat };
}

function toInt(value, max) {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 && number <= max ? number : NaN;
}

// e.g. my-bucket.s3.amazonaws.com, my-bucket.s3.ap-northeast-2.amazonaws.com
function parseS3Domain(domainName) {
  const match = /^(.+)\.s3(?:[.-]([a-z0-9-]+))?\.amazonaws\.com$/.exec(domainName);
  return match && { bucket: match[1], region: match[2] ?? 'us-east-1' };
}

function getS3Client(region) {
  if (!s3Clients.has(region)) {
    s3Clients.set(region, new S3Client({ region, followRegionRedirects: true }));
  }
  return s3Clients.get(region);
}
