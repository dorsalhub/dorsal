import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


class IPFSHasher:
    """
    Simulates the IPFS `add --only-hash` DAG builder (CIDv1, DAG-PB, UnixFS).
    Mimics the hashlib interface (update, hexdigest) to fit into FileHasher.
    """

    IPFS_CHUNK_SIZE = 256 * 1024

    _cid_module: Any
    _unixfs_pb2: Any
    _merkledag_pb2: Any

    def __init__(self):
        try:
            import cid
            from dorsal.file.utils.proto import unixfs_pb2, merkledag_pb2

            self._cid_module = cid
            self._unixfs_pb2 = unixfs_pb2
            self._merkledag_pb2 = merkledag_pb2
        except ImportError as err:
            raise ImportError(
                "IPFS dependencies or compiled protobufs missing. "
                "Run `pip install dorsalhub[ipfs]` and ensure protos are compiled."
            ) from err

        self._buffer = bytearray()
        self._links = []
        self._total_file_size = 0

    def _hash_pb_node(self, pb_node_bytes: bytes) -> bytes:
        """Hashes the protobuf node and wraps it in a SHA2-256 multihash."""
        node_hash = hashlib.sha256(pb_node_bytes).digest()
        # 0x12 = sha2-256, 0x20 = 32 bytes length
        return b"\x12\x20" + node_hash

    def _process_chunk(self, chunk_data: bytes):
        """Builds a UnixFS File leaf node, hashes it, and stores the link."""
        chunk_size = len(chunk_data)

        unixfs_data = self._unixfs_pb2.Data()
        unixfs_data.Type = self._unixfs_pb2.Data.File
        unixfs_data.filesize = chunk_size

        # IPFS omits the Data field entirely if the chunk is empty
        if chunk_data:
            unixfs_data.Data = chunk_data

        pb_node = self._merkledag_pb2.PBNode()
        pb_node.Data = unixfs_data.SerializeToString(deterministic=True)
        pb_node_bytes = pb_node.SerializeToString(deterministic=True)

        multihash = self._hash_pb_node(pb_node_bytes)
        self._links.append((multihash, len(pb_node_bytes), chunk_size))
        self._total_file_size += chunk_size

    def update(self, chunk: bytes):
        """Accumulates pipeline chunks and slices them into strict 256KB blocks."""
        self._buffer.extend(chunk)

        while len(self._buffer) >= self.IPFS_CHUNK_SIZE:
            block = bytes(self._buffer[: self.IPFS_CHUNK_SIZE])
            self._process_chunk(block)
            del self._buffer[: self.IPFS_CHUNK_SIZE]

    def hexdigest(self) -> str:
        """Builds the final root DAG node and returns the CIDv1 string."""
        if self._buffer:
            self._process_chunk(bytes(self._buffer))
            self._buffer.clear()

        # Handle empty file edge case
        if not self._links:
            self._process_chunk(b"")

        # If the file fits in a single chunk, IPFS does not create a wrapper root node
        if len(self._links) == 1:
            root_multihash = self._links[0][0]
        else:
            unixfs_root = self._unixfs_pb2.Data()
            unixfs_root.Type = self._unixfs_pb2.Data.File
            unixfs_root.filesize = self._total_file_size

            pb_root = self._merkledag_pb2.PBNode()

            for link_hash, link_tsize, block_size in self._links:
                unixfs_root.blocksizes.append(block_size)

                pb_link = pb_root.Links.add()
                pb_link.Hash = link_hash
                pb_link.Tsize = link_tsize
                pb_link.Name = ""

            pb_root.Data = unixfs_root.SerializeToString(deterministic=True)
            root_multihash = self._hash_pb_node(pb_root.SerializeToString(deterministic=True))

        # Generate CIDv1: base32/base58 encoded, cidv1 version, dag-pb codec
        cid_obj = self._cid_module.make_cid(1, "dag-pb", root_multihash)
        return cid_obj.encode().decode("utf-8")
