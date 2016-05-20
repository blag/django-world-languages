from urllib.request import urlretrieve

from tqdm import tqdm


def urlopen_with_progress(url):
    def my_hook(t):
        """
        Wraps tqdm instance. Don't forget to close() or __exit__() the tqdm instance
        once you're done (easiest using a context manager, eg: `with` syntax)

        Example
        -------

        >>> with tqdm(...) as t:
        ...     reporthook = my_hook(t)
        ...     urllib.urlretrieve(..., reporthook=reporthook)
        """
        last_b = [0]

        def inner(b=1, bsize=1, tsize=None):
            """
            b     : int, optional    Number of blocks just transferred [default: 1]
            bsize : int, optional    Size of each block (in tqdm units) [default: 1]
            tsize : int, optional    Total size (in tqdm units). If [default: None]
                                     remains unchanged.
            """
            if tsize is not None:
                t.total = tsize
            t.update((b - last_b[0]) * bsize)
            last_b[0] = b
        return inner

    with tqdm(unit='B', unit_scale=True, miniters=1,
              desc="Downloading languages file...") as t:
        filename, _ = urlretrieve(url, reporthook=my_hook(t))

    with open(filename, 'r') as f:
        return f.read()
