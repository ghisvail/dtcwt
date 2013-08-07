import numpy as np
from scipy.signal import convolve2d

def as_column_vector(v):
    """Return v as a column vector with shape (N,1)."""
    v = np.atleast_2d(v)
    if v.shape[0] == 1:
        return v.T
    else:
        return v

def _centered(arr, newsize):
    # Return the center newsize portion of the array.
    # (Shamelessly cribbed from scipy.)
    newsize = np.asarray(newsize)
    currsize = np.array(arr.shape)
    startind = (currsize - newsize) // 2
    endind = startind + newsize
    myslice = [slice(startind[k], endind[k]) for k in range(len(endind))]
    return arr[tuple(myslice)]

# This is to allow easy replacement of these later with, possibly, GPU versions
_rfft = np.fft.rfft
_irfft = np.fft.irfft

def _column_convolve(X, h):
    """Convolve the columns of X with h returning only the 'valid' section,
    i.e. those values unaffected by zero padding.

    """
    h = h.flatten()
    h_size = h.shape[0]
    full_size = X.shape[0] + h_size - 1

    # For small arrays, convolving directly is often faster
    if full_size < 32:
        return convolve2d(X, as_column_vector(h), 'valid')

    # Always use 2**n-sized FFT
    fsize = 2 ** np.ceil(np.log2(full_size)).astype(int)

    # Take FFT down columns
    Xfft = _rfft(X, n=fsize, axis=0)

    # Take FFT of input vector
    hfft = _rfft(h, n=fsize, axis=0)

    # Column-wise multiply. I.e. scale rows of Xfft by hfft
    Xfft = Xfft * hfft[:,np.newaxis]

    # Invert
    Xconv = _irfft(Xfft, n=fsize, axis=0)[:full_size,:].real
    Xvalid = _centered(Xconv, (abs(X.shape[0] - h_size) + 1, X.shape[1]))

    return Xvalid

def reflect(x, minx, maxx):
    """Reflect the values in matrix x about the scalar values minx and maxx.
    Hence a vector x containing a long linearly increasing series is converted
    into a waveform which ramps linearly up and down between minx and maxx.  If
    x contains integers and minx and maxx are (integers + 0.5), the ramps will
    have repeated max and min samples.
   
    Nick Kingsbury, Cambridge University, January 1999.
    
    """

    # Copy x to avoid in-place modification
    y = np.array(x, copy=True)

    # Reflect y in maxx.
    t = y > maxx
    y[t] = 2*maxx - y[t]

    while np.any(y < minx):
        # Reflect y in minx.
        t = y < minx
        y[t] = 2*minx - y[t]

        # Reflect y in maxx.
        t = y > maxx
        y[t] = 2*maxx - y[t]

    return y

def colfilter(X, h):
    """Filter the columns of image X using filter vector h, without decimation.
    If length(h) is odd, each output sample is aligned with each input sample
    and Y is the same size as X.  If length(h) is even, each output sample is
    aligned with the mid point of each pair of input samples, and size(Y) =
    size(X) + [1 0]; 

    Cian Shaffrey, Nick Kingsbury Cambridge University, August 2000

    """
    
    # Interpret all inputs as arrays
    X = np.array(X)
    h = as_column_vector(h)

    r, c = X.shape
    m = h.shape[0]
    m2 = np.fix(m*0.5)

    # Symmetrically extend with repeat of end samples.
    # Use 'reflect' so r < m2 works OK.
    xe = reflect(np.arange(-m2, r+m2, dtype=np.int), -0.5, r-0.5)

    # Perform filtering on the columns of the extended matrix X(xe,:), keeping
    # only the 'valid' output samples, so Y is the same size as X if m is odd.
    Y = _column_convolve(X[xe,:], h)

    return Y

def coldfilt(X, ha, hb):
    """Filter the columns of image X using the two filters ha and hb =
    reverse(ha).  ha operates on the odd samples of X and hb on the even
    samples.  Both filters should be even length, and h should be approx linear
    phase with a quarter sample advance from its mid pt (ie |h(m/2)| > |h(m/2 +
    1)|).

                      ext        top edge                     bottom edge       ext
    Level 1:        !               |               !               |               !
    odd filt on .    b   b   b   b   a   a   a   a   a   a   a   a   b   b   b   b   
    odd filt on .      a   a   a   a   b   b   b   b   b   b   b   b   a   a   a   a
    Level 2:        !               |               !               |               !
    +q filt on x      b       b       a       a       a       a       b       b       
    -q filt on o          a       a       b       b       b       b       a       a

    The output is decimated by two from the input sample rate and the results
    from the two filters, Ya and Yb, are interleaved to give Y.  Symmetric
    extension with repeated end samples is used on the composite X columns
    before each filter is applied.

    Raises ValueError if the number of rows in X is not a multiple of 4, the
    length of ha does not match hb or the lengths of ha or hb are non-even.

    Cian Shaffrey, Nick Kingsbury Cambridge University, August 2000

    """
    # Make sure all inputs are arrays
    X = np.array(X)
    ha = np.array(ha)
    hb = np.array(hb)

    r, c = X.shape
    if r % 4 != 0:
        raise ValueError('No. of rows in X must be a multiple of 4')

    if ha.shape != hb.shape:
        raise ValueError('Shapes of ha and hb must be the same')

    if ha.shape[0] % 2 != 0:
        raise ValueError('Lengths of ha and hb must be even')

    m = ha.shape[0]
    m2 = np.fix(m*0.5)

    # Set up vector for symmetric extension of X with repeated end samples.
    xe = reflect(np.arange(-m, r+m), -0.5, r-0.5)

    # Select odd and even samples from ha and hb. Note that due to 0-indexing
    # 'odd' and 'even' are not perhaps what you might expect them to be.
    hao = as_column_vector(ha[0:m:2])
    hae = as_column_vector(ha[1:m:2])
    hbo = as_column_vector(hb[0:m:2])
    hbe = as_column_vector(hb[1:m:2])
    t = np.arange(5, r+2*m-2, 4)
    r2 = r/2;
    Y = np.zeros((r2,c))

    if np.sum(ha*hb) > 0:
       s1 = np.arange(0, r2, 2)
       s2 = s1 + 1
    else:
       s2 = np.arange(0, r2, 2)
       s1 = s2 + 1
    
    # Perform filtering on columns of extended matrix X(xe,:) in 4 ways. 
    Y[s1,:] = _column_convolve(X[xe[t-1],:],hao) + _column_convolve(X[xe[t-3],:],hae)
    Y[s2,:] = _column_convolve(X[xe[t],:],hbo) + _column_convolve(X[xe[t-2],:],hbe)

    return Y

def colifilt(X, ha, hb):
    """ Filter the columns of image X using the two filters ha and hb =
    reverse(ha).  ha operates on the odd samples of X and hb on the even
    samples.  Both filters should be even length, and h should be approx linear
    phase with a quarter sample advance from its mid pt (ie |h(m/2)| > |h(m/2 +
    1)|).
    
                      ext       left edge                      right edge       ext
    Level 2:        !               |               !               |               !
    +q filt on x      b       b       a       a       a       a       b       b       
    -q filt on o          a       a       b       b       b       b       a       a
    Level 1:        !               |               !               |               !
    odd filt on .    b   b   b   b   a   a   a   a   a   a   a   a   b   b   b   b   
    odd filt on .      a   a   a   a   b   b   b   b   b   b   b   b   a   a   a   a
   
    The output is interpolated by two from the input sample rate and the
    results from the two filters, Ya and Yb, are interleaved to give Y.
    Symmetric extension with repeated end samples is used on the composite X
    columns before each filter is applied.
   
    Cian Shaffrey, Nick Kingsbury Cambridge University, August 2000
    
    Modified to be fast if X = 0, May 2002.

    """
    # Make sure all inputs are arrays
    X = np.array(X)
    ha = np.array(ha)
    hb = np.array(hb)

    r, c = X.shape
    if r % 2 != 0:
        raise ValueError('No. of rows in X must be a multiple of 2')

    if ha.shape != hb.shape:
        raise ValueError('Shapes of ha and hb must be the same')

    if ha.shape[0] % 2 != 0:
        raise ValueError('Lengths of ha and hb must be even')

    m = ha.shape[0]
    m2 = np.fix(m*0.5)

    Y = np.zeros((r*2,c))
    if not np.any(np.nonzero(X[:])[0]):
        return Y

    if m2 % 2 == 0:
        # m/2 is even, so set up t to start on d samples.
        # Set up vector for symmetric extension of X with repeated end samples.
        # Use 'reflect' so r < m2 works OK.
        xe = reflect(np.arange(-m2, r+m2, dtype=np.int), -0.5, r-0.5)
       
        t = np.arange(3, r+m, 2)
        if np.sum(ha*hb) > 0:
            ta = t
            tb = t - 1
        else:
            ta = t - 1
            tb = t
       
        # Select odd and even samples from ha and hb. Note that due to 0-indexing
        # 'odd' and 'even' are not perhaps what you might expect them to be.
        hao = as_column_vector(ha[0:m:2])
        hae = as_column_vector(ha[1:m:2])
        hbo = as_column_vector(hb[0:m:2])
        hbe = as_column_vector(hb[1:m:2])
       
        s = np.arange(0,r*2,4)
       
        Y[s,:]   = _column_convolve(X[xe[tb-2],:],hae)
        Y[s+1,:] = _column_convolve(X[xe[ta-2],:],hbe)
        Y[s+2,:] = _column_convolve(X[xe[tb  ],:],hao)
        Y[s+3,:] = _column_convolve(X[xe[ta  ],:],hbo)
    else:
        # m/2 is odd, so set up t to start on b samples.
        # Set up vector for symmetric extension of X with repeated end samples.
        # Use 'reflect' so r < m2 works OK.
        xe = reflect(np.arange(-m2, r+m2, dtype=np.int), -0.5, r-0.5)

        t = np.arange(2, r+m-1, 2)
        if np.sum(ha*hb) > 0:
            ta = t
            tb = t - 1
        else:
            ta = t - 1
            tb = t
       
        # Select odd and even samples from ha and hb. Note that due to 0-indexing
        # 'odd' and 'even' are not perhaps what you might expect them to be.
        hao = as_column_vector(ha[0:m:2])
        hae = as_column_vector(ha[1:m:2])
        hbo = as_column_vector(hb[0:m:2])
        hbe = as_column_vector(hb[1:m:2])
       
        s = np.arange(0,r*2,4)
       
        Y[s,:]   = _column_convolve(X[xe[tb],:],hao)
        Y[s+1,:] = _column_convolve(X[xe[ta],:],hbo)
        Y[s+2,:] = _column_convolve(X[xe[tb],:],hae)
        Y[s+3,:] = _column_convolve(X[xe[ta],:],hbe)

    return Y

# vim:sw=4:sts=4:et
