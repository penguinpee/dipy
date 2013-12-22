from __future__ import division
import numpy as np
from dipy.reconst.cache import Cache
from dipy.reconst.multi_voxel import multi_voxel_fit
from dipy.reconst.shm import real_sph_harm
from dipy.core.gradients import gradient_table
from scipy.special import genlaguerre, gamma, hyp2f1
from dipy.core.geometry import cart2sphere
from math import factorial

class ShoreModel(Cache):

    r"""Simple Harmonic Oscillator based Reconstruction and Estimation 
    (SHORE) [1]_ of the diffusion signal.

    The main idea is to model the diffusion signal as a linear combination of
    continuous functions $\phi_i$,

    ..math::
        :nowrap:
            \begin{equation}
                S(\mathbf{q})= \sum_{i=0}^I  c_{i} \phi_{i}(\mathbf{q}).
            \end{equation}

    where $\mathbf{q}$ is the wavector which corresponds to different gradient
    directions. Numerous continuous functions $\phi_i$ can be used to model 
    $S$. Some are presented in [2,3,4]_.

    From the $c_i$ coefficients, there exist analytical formulae to estimate 
    the ODF, the return to the origin porbability (RTOP), the mean square 
    displacement (MSD), amongst others [5]_.

    References
    ----------
    .. [1] Ozarslan E. et. al, "Simple harmonic oscillator based reconstruction
           and estimation for one-dimensional q-space magnetic resonance
           1D-SHORE)", eapoc Intl Soc Mag Reson Med, vol. 16, p. 35., 2008.

    .. [2] Merlet S. et. al, "Continuous diffusion signal, EAP and ODF
           estimation via Compressive Sensing in diffusion MRI", Medical
           Image Analysis, 2013.

    .. [3] Rathi Y. et. al, "Sparse multi-shell diffusion imaging", MICCAI,
           2011.

    .. [4] Cheng J. et. al, "Theoretical Analysis and eapactical Insights on
           EAP Estimation via a Unified HARDI Framework", MICCAI workshop on
           Computational Diffusion MRI, 2011.

    .. [5] Ozarslan E. et. al, "Mean apparent propagator (MAP) MRI: A novel 
           diffusion imaging method for mapping tissue microstructure", 
           NeuroImage, 2013.
    """

    def __init__(self,
                 gtab,
                 radial_order=6,
                 zeta=700,
                 lambdaN=1e-8,
                 lambdaL=1e-8):
        r""" Analytical and continuous modeling of the diffusion signal with
        respect to the SHORE basis [1,2]_.
        This implementation is a modification of SHORE presented in [1]_.
        The modification was made to obtain the same ordering of the basis 
        presented in [2,3]_.

        The main idea is to model the diffusion signal as a linear 
        combination of continuous functions $\phi_i$,

        ..math::
            :nowrap:
                \begin{equation}
                    S(\mathbf{q})= \sum_{i=0}^I  c_{i} \phi_{i}(\mathbf{q}).
                \end{equation}

        where $\mathbf{q}$ is the wavector which corresponds to different 
        gradient directions.

        From the $c_i$ coefficients, there exists an analytical formula to
        estimate the ODF.


        Parameters
        ----------
        gtab : GradientTable,
            gradient directions and bvalues container class
        radial_order : unsigned int,
            an even integer that represent the order of the basis
        zeta : unsigned int,
            scale factor
        lambdaN : float,
            radial regularisation constant
        lambdaL : float,
            angular regularisation constant
        tau : float,
            diffusion time. By default the value that makes q equal to the
            square root of the b-value.

        References
        ----------
        .. [1] Merlet S. et. al, "Continuous diffusion signal, EAP and 
        ODF estimation via Compressive Sensing in diffusion MRI", Medical
        Image Analysis, 2013.

        .. [2] Cheng J. et. al, "Theoretical Analysis and eapactical Insights
        on EAP Estimation via a Unified HARDI Framework", MICCAI workshop on 
        Computational Diffusion MRI, 2011.

        .. [3] Ozarslan E. et. al, "Mean apparent propagator (MAP) MRI: A novel 
           diffusion imaging method for mapping tissue microstructure", 
           NeuroImage, 2013.

        Examples
        --------
        In this example, where the data, gradient table and sphere tessellation
        used for reconstruction are provided, we model the diffusion signal 
        with respect to the SHORE basis and compute the real and analytical
        ODF.

        from dipy.data import get_data,get_sphere
        sphere = get_sphere('symmetric724')
        fimg, fbvals, fbvecs = get_data('ISBI_testing_2shells_table')
        bvals, bvecs = read_bvals_bvecs(fbvals, fbvecs)
        gtab = gradient_table(bvals, bvecs)
        from dipy.sims.voxel import SticksAndBall
        data, golden_directions = SticksAndBall(gtab, d=0.0015,
                                                S0=1, angles=[(0, 0), (90, 0)],
                                                fractions=[50, 50], snr=None)
        from dipy.reconst.canal import ShoreModel
        radial_order = 4
        zeta = 700
        asm = ShoreModel(gtab, radial_order=radial_order, zeta=zeta, 
                         lambdaN=1e-8, lambdaL=1e-8)
        asmfit = asm.fit(data)
        odf= asmfit.odf(sphere)
        """

        self.bvals = gtab.bvals
        self.bvecs = gtab.bvecs
        self.gtab = gtab
        if radial_order > 0 and not(bool(radial_order % 2)):
            self.radial_order = radial_order
        else:
            msg = "radial_order must be a non-zero even positive number."
            raise ValueError(msg)
        self.zeta = zeta
        self.lambdaL = lambdaL
        self.lambdaN = lambdaN
        if (gtab.big_delta is None) or (gtab.small_delta is None):
            self.tau = 1 / (4 * np.pi ** 2)
        else:
            self.tau = gtab.big_delta - gtab.small_delta / 3.0

    @multi_voxel_fit
    def fit(self, data):
        Lshore = l_shore(self.radial_order)
        Nshore = n_shore(self.radial_order)
        # Generate the SHORE basis
        M = self.cache_get('shore_matrix', key=self.gtab)
        if M is None:
            M = shore_matrix(self.radial_order,  self.zeta, self.gtab, self.tau)
            self.cache_set('shore_matrix', self.gtab, M)

        # Compute the signal coefficients in SHORE basis
        pseudoInv = np.dot(np.linalg.inv(np.dot(M.T, M) + self.lambdaN * Nshore + self.lambdaL * Lshore), M.T)
        coef = np.dot(pseudoInv, data)

        signal_0 = 0

        for n in range(int(self.radial_order / 2) + 1):
            signal_0 += coef[n] * genlaguerre(n, 0.5)(0) * \
                ((factorial(n)) / (2 * np.pi * (self.zeta ** 1.5) * gamma(n + 1.5))) ** 0.5

        coef = coef / signal_0

        return ShoreFit(self, coef)


class ShoreFit():

    def __init__(self, model, shore_coef):
        """ Calculates diffusion properties for a single voxel

        Parameters
        ----------
        model : object,
            AnalyticalModel
        shore_coef : 1d ndarray,
            shore coefficients
        """

        self.model = model
        self._shore_coef = shore_coef
        self.gtab = model.gtab
        self.radial_order = model.radial_order
        self.zeta = model.zeta

    def pdf_grid(self, gridsize, radius_max):
        r""" Applies the analytical FFT on $S$ to generate the diffusion
        propagator. This is calculated on a discrete 3D grid in order to
        obtain an EAP similar to that which is obtained with DSI.

        Parameters
        ----------
        gridsize : unsigned int
            dimension of the propagator grid
        radius_max : float
            maximal radius in which to compute the propagator
        
        Returns
        -------
        eap : ndarray
            the ensemble average propagator in the 3D grid

        """
        eap = np.zeros((gridsize, gridsize, gridsize))
        # Create the grid in which to compute the pdf
        rgrid, rtab = create_rspace(gridsize, radius_max)
        psi = self.model.cache_get('shore_matrix_pdf', key=gridsize)
        if psi is None:
            psi = shore_matrix_pdf(self.radial_order,  self.zeta, rtab)
            self.model.cache_set('shore_matrix_pdf', gridsize, psi)

        propagator = np.dot(psi, self._shore_coef)
        # fill real space
        for i in range(len(rgrid)):
            qx, qy, qz = rgrid[i]
            eap[qx, qy, qz] += propagator[i]
        # normalize by the area of the propagator
        eap = eap * (2 * radius_max / (gridsize - 1)) ** 3

        return np.clip(eap, 0, eap.max())

    def pdf(self, r_points):
        """ Diffusion propagator on a given set of real points.
        """
        psi = self.model.cache_get('shore_matrix_pdf', key=r_points.sum())
        if psi is None:
            psi = shore_matrix_pdf(self.radial_order,  self.zeta, r_points)
            self.model.cache_set('shore_matrix_pdf', r_points.sum(), psi)

        eap = np.dot(psi, self._shore_coef)

        return np.clip(eap, 0, eap.max())

    def odf_sh(self):
        r""" Calculates the real analytical ODF in terms of Spherical Harmonics.
        """
        # Number of Spherical Harmonics involved in the estimation
        J = (self.radial_order + 1) * (self.radial_order + 2) / 2

        # Compute the Spherical Harmonics Coefficients
        c_sh = np.zeros(J)
        counter = 0

        for l in range(0, self.radial_order + 1, 2):
            for n in range(l, int((self.radial_order + l) / 2) + 1):
                for m in range(-l, l + 1):

                    j = int(l + m + (2 * np.array(range(0, l, 2)) + 1).sum())

                    Cnl = ((-1) ** (n - l / 2)) / (2.0 * (4.0 * np.pi ** 2 * self.zeta) ** (3.0 / 2.0)) * ((2.0 * (
                        4.0 * np.pi ** 2 * self.zeta) ** (3.0 / 2.0) * factorial(n - l)) / (gamma(n + 3.0 / 2.0))) ** (1.0 / 2.0)
                    Gnl = (gamma(l / 2 + 3.0 / 2.0) * gamma(3.0 / 2.0 + n)) / (gamma(
                        l + 3.0 / 2.0) * factorial(n - l)) * (1.0 / 2.0) ** (-l / 2 - 3.0 / 2.0)
                    Fnl = hyp2f1(-n + l, l / 2 + 3.0 / 2.0, l + 3.0 / 2.0, 2.0)

                    c_sh[j] += self._shore_coef[counter] * Cnl * Gnl * Fnl
                    counter += 1

        return c_sh

    def odf(self, sphere):
        r""" Calculates the ODF for a given discrete sphere.
        """
        upsilon = self.model.cache_get('shore_matrix_odf', key=sphere)
        if upsilon is None:
            upsilon = shore_matrix_odf(
                self.radial_order,  self.zeta, sphere.vertices)
            self.model.cache_set('shore_matrix_odf', sphere, upsilon)

        odf = np.dot(upsilon, self._shore_coef)
        return odf

    def rtop_signal(self):
        r""" Calculates the analytical return to origin probability (RTOP)
        from the signal [1]_.  
        
        References
        ----------
        .. [1] Ozarslan E. et. al, "Mean apparent propagator (MAP) MRI: A novel 
        diffusion imaging method for mapping tissue microstructure", 
        NeuroImage, 2013.
        """
        rtop = 0
        c = self._shore_coef

        for n in range(int(self.radial_order / 2) + 1):
            rtop +=  c[n] * (-1) ** n * \
                ((16 * np.pi * self.zeta ** 1.5 * gamma(n + 1.5)) / (
                 factorial(n))) ** 0.5

        return np.clip(rtop, 0, rtop.max())

    def rtop_pdf(self):
        r""" Calculates the analytical return to origin probability (RTOP) 
        from the pdf [1]_.  
        
        References
        ----------
        .. [1] Ozarslan E. et. al, "Mean apparent propagator (MAP) MRI: A novel 
        diffusion imaging method for mapping tissue microstructure", 
        NeuroImage, 2013.
        """
        rtop = 0
        c = self._shore_coef
        for n in range(int(self.radial_order / 2) + 1):
            rtop += c[n] * (-1) ** n * \
                ((4 * np.pi ** 2 * self.zeta ** 1.5 * factorial(n)) / (gamma(n + 1.5))) ** 0.5 * \
                genlaguerre(n, 0.5)(0)

        return np.clip(rtop, 0, rtop.max())

    def msd(self):
        r""" Calculates the analytical mean squared displacement (MSD) [1]_

        ..math::
            :nowrap:
                \begin{equation}
                    MSD:{DSI}=\int_{-\infty}^{\infty}\int_{-\infty}^{\infty}\int_{-\infty}^{\infty} P(\hat{\mathbf{r}}) \cdot \hat{\mathbf{r}}^{2} \ dr_x \ dr_y \ dr_z
                \end{equation}

        where $\hat{\mathbf{r}}$ is a point in the 3D propagator space (see Wu et. al [1]_).

        References
        ----------
        .. [1] Wu Y. et. al, "Hybrid diffusion imaging", NeuroImage, vol 36,
        p. 617-629, 2007.
        """
        msd = 0
        c = self._shore_coef

        for n in range(int(self.radial_order / 2) + 1):
            msd += c[n]  * (-1) ** n *\
                (9 * (gamma(n + 1.5)) / (8 * np.pi ** 6  *  self.zeta ** 3.5 * factorial(n))) ** 0.5 *\
                hyp2f1(-n, 2.5, 1.5, 2)

        return np.clip(msd, 0, msd.max())

    @property
    def shore_coeff(self):
        """The SHORE coefficients
        """
        return self._shore_coef


def shore_matrix(radial_order, zeta, gtab, tau=1 / (4 * np.pi ** 2)):
    r"""Compute the SHORE matrix for modified Merlet's 3D-SHORE [1]_

    ..math::
            :nowrap:
                \begin{equation}
                    \textbf{E}(q\textbf{u})=\sum_{l=0, even}^{N_{max}}
                                            \sum_{n=l}^{(N_{max}+l)/2}
                                            \sum_{m=-l}^l c_{nlm}
                                            \phi_{nlm}(q\textbf{u})
                \end{equation}

    where $\phi_{nlm}$ is
    ..math::
            :nowrap:
                \begin{equation}
                    \phi_{nlm}^{SHORE}(q\textbf{u})=\Biggl[\dfrac{2(n-l)!}
                        {\zeta^{3/2} \Gamma(n+3/2)} \Biggr]^{1/2} 
                        \Biggl(\dfrac{q^2}{\zeta}\Biggr)^{l/2} 
                        exp\Biggl(\dfrac{-q^2}{2\zeta}\Biggr) 
                        L^{l+1/2}_{n-l} \Biggl(\dfrac{q^2}{\zeta}\Biggr)
                        Y_l^m(\textbf{u}).
                \end{equation}

    Parameters
    ----------
    radial_order : unsigned int,
        an even integer that represent the order of the basis
    zeta : unsigned int,
        scale factor
    gtab : GradientTable,
        gradient directions and bvalues container class
    tau : float,
        diffusion time. By default the value that makes q=sqrt(b).

    References
    ----------
    .. [1] Merlet S. et. al, "Continuous diffusion signal, EAP and 
    ODF estimation via Compressive Sensing in diffusion MRI", Medical
    Image Analysis, 2013.

    """

    qvals = np.sqrt(gtab.bvals / (4 * np.pi ** 2 * tau))
    bvecs = gtab.bvecs

    qgradients = qvals[:, None] * bvecs

    r, theta, phi = cart2sphere(qgradients[:, 0], qgradients[:, 1],
                                qgradients[:, 2])
    theta[np.isnan(theta)] = 0
    F = radial_order / 2
    n_c = np.round(1 / 6.0 * (F + 1) * (F + 2) * (4 * F + 3))
    M = np.zeros((r.shape[0], n_c))

    counter = 0
    for l in range(0, radial_order + 1, 2):
        for n in range(l, int((radial_order + l) / 2) + 1):
            for m in range(-l, l + 1):
                M[:, counter] = real_sph_harm(m, l, theta, phi) * \
                    genlaguerre(n - l, l + 0.5)(r ** 2 / zeta) * \
                    np.exp(- r ** 2 / (2.0 * zeta)) * \
                    _kappa(zeta, n, l) * \
                    (r ** 2 / zeta) ** (l / 2)
                counter += 1
    return M


def _kappa(zeta, n, l):
    return np.sqrt((2 * factorial(n - l)) / (zeta ** 1.5 * gamma(n + 1.5)))


def shore_matrix_pdf(radial_order, zeta, rtab):
    r"""Compute the SHORE propagator matrix [1]_"

    Parameters
    ----------
    radial_order : unsigned int,
        an even integer that represent the order of the basis
    zeta : unsigned int,
        scale factor
    rtab : array, shape (N,3)
        real space points in which calculates the pdf

    References
    ----------
    .. [1] Merlet S. et. al, "Continuous diffusion signal, EAP and 
    ODF estimation via Compressive Sensing in diffusion MRI", Medical
    Image Analysis, 2013.
    """

    r, theta, phi = cart2sphere(rtab[:, 0], rtab[:, 1], rtab[:, 2])
    theta[np.isnan(theta)] = 0
    F = radial_order / 2
    n_c = np.round(1 / 6.0 * (F + 1) * (F + 2) * (4 * F + 3))
    psi = np.zeros((r.shape[0], n_c))
    counter = 0
    for l in range(0, radial_order + 1, 2):
        for n in range(l, int((radial_order + l) / 2) + 1):
            for m in range(-l, l + 1):
                psi[:, counter] = real_sph_harm(m, l, theta, phi) * \
                    genlaguerre(n - l, l + 0.5)(4 * np.pi ** 2 * zeta * r ** 2 ) *\
                    np.exp(-2 * np.pi ** 2 * zeta * r ** 2) *\
                    _kappa_pdf(zeta, n, l) *\
                    (4 * np.pi ** 2 * zeta * r ** 2) ** (l / 2) * \
                    (-1) ** (n - l / 2)
                counter += 1
    return psi


def _kappa_pdf(zeta, n, l):
    return np.sqrt((16 * np.pi ** 3 * zeta ** 1.5 * factorial(n - l)) / gamma(n + 1.5))


def shore_matrix_odf(radial_order, zeta, sphere_vertices):
    r"""Compute the SHORE ODF matrix [1]_"

    Parameters
    ----------
    radial_order : unsigned int,
        an even integer that represent the order of the basis
    zeta : unsigned int,
        scale factor
    sphere_vertices : array, shape (N,3)
        vertices of the odf sphere
    
    References
    ----------
    .. [1] Merlet S. et. al, "Continuous diffusion signal, EAP and 
    ODF estimation via Compressive Sensing in diffusion MRI", Medical
    Image Analysis, 2013.    
    """

    r, theta, phi = cart2sphere(sphere_vertices[:, 0], sphere_vertices[:, 1],
                                sphere_vertices[:, 2])
    theta[np.isnan(theta)] = 0
    F = radial_order / 2
    n_c = np.round(1 / 6.0 * (F + 1) * (F + 2) * (4 * F + 3))
    upsilon = np.zeros((len(sphere_vertices), n_c))
    counter = 0
    for l in range(0, radial_order + 1, 2):
        for n in range(l, int((radial_order + l) / 2) + 1):
            for m in range(-l, l + 1):
                upsilon[:, counter] = (-1) ** (n - l / 2.0) * _kappa_odf(zeta, n, l) * \
                    hyp2f1(l - n, l / 2.0 + 1.5, l + 1.5, 2.0) * \
                    real_sph_harm(m, l, theta, phi)
                counter += 1

    return upsilon


def _kappa_odf(zeta, n, l):
    return np.sqrt((gamma(l / 2.0 + 1.5) ** 2 * gamma(n + 1.5) * 2 ** (l + 3)) /
                   (16 * np.pi ** 3 * (zeta) ** 1.5 * factorial(n - l) * gamma(l + 1.5) ** 2))


def l_shore(radial_order):
    "Returns the angular regularisation matrix for SHORE basis"
    F = radial_order / 2
    n_c = np.round(1 / 6.0 * (F + 1) * (F + 2) * (4 * F + 3))
    diagL = np.zeros(n_c)
    counter = 0
    for l in range(0, radial_order + 1, 2):
        for n in range(l, int((radial_order + l) / 2) + 1):
            for m in range(-l, l + 1):
                diagL[counter] = (l * (l + 1)) ** 2
                counter += 1

    return np.diag(diagL)


def n_shore(radial_order):
    "Returns the angular regularisation matrix for SHORE basis"
    F = radial_order / 2
    n_c = np.round(1 / 6.0 * (F + 1) * (F + 2) * (4 * F + 3))
    diagN = np.zeros(n_c)
    counter = 0
    for l in range(0, radial_order + 1, 2):
        for n in range(l, int((radial_order + l) / 2) + 1):
            for m in range(-l, l + 1):
                diagN[counter] = (n * (n + 1)) ** 2
                counter += 1

    return np.diag(diagN)


def create_rspace(gridsize, radius_max):
    """ Create the real space table, that contains the points in which 
        to compute the pdf.

    Parameters
    ----------
    gridsize : unsigned int
        dimension of the propagator grid
    radius_max : float
        maximal radius in which compute the propagator

    Returns
    -------
    vecs : array, shape (N,3)
        positions of the pdf points in a 3D matrix

    tab : array, shape (N,3)
        real space points in which calculates the pdf
    """

    radius = gridsize // 2
    vecs = []
    for i in range(-radius, radius + 1):
        for j in range(-radius, radius + 1):
            for k in range(-radius, radius + 1):
                vecs.append([i, j, k])

    vecs = np.array(vecs, dtype=np.float32)
    tab = vecs / radius
    tab = tab * radius_max
    vecs = vecs + radius

    return vecs, tab

def shore_indices(radial_order, index):
    r"""Given the basis order and the index, return the shore indices n, l, m
    for modified Merlet's 3D-SHORE
    ..math::
            :nowrap:
                \begin{equation}
                    \textbf{E}(q\textbf{u})=\sum_{l=0, even}^{N_{max}}
                                            \sum_{n=l}^{(N_{max}+l)/2}
                                            \sum_{m=-l}^l c_{nlm}
                                            \phi_{nlm}(q\textbf{u})
                \end{equation}

    where $\phi_{nlm}$ is
    ..math::
            :nowrap:
                \begin{equation}
                    \phi_{nlm}^{SHORE}(q\textbf{u})=\Biggl[\dfrac{2(n-l)!}
                        {\zeta^{3/2} \Gamma(n+3/2)} \Biggr]^{1/2} 
                        \Biggl(\dfrac{q^2}{\zeta}\Biggr)^{l/2} 
                        exp\Biggl(\dfrac{-q^2}{2\zeta}\Biggr) 
                        L^{l+1/2}_{n-l} \Biggl(\dfrac{q^2}{\zeta}\Biggr)
                        Y_l^m(\textbf{u}).
                \end{equation}

    Parameters
    ----------
    radial_order : unsigned int
        an even integer that represent the maximal order of the basis
    index : unsigned int
        index of the coefficients, start from 0

    Returns
    -------
    n :  unsigned int
        the index n of the modified shore basis
    l :  unsigned int
        the index l of the modified shore basis
    m :  unsigned int
        the index m of the modified shore basis        
    """

    F = radial_order / 2
    n_c = np.round(1 / 6.0 * (F + 1) * (F + 2) * (4 * F + 3))
    n_i = 0
    l_i = 0
    m_i = 0

    if n_c < (index + 1):
        msg = "The index is higher than the number of coefficients of the truncated basis."
        raise ValueError(msg)
    else:
        counter = 0
        for l in range(0, radial_order + 1, 2):
            for n in range(l, int((radial_order + l) / 2) + 1):
                for m in range(-l, l + 1):
                    if counter == index:
                        n_i = n
                        l_i = l
                        m_i = m
                    counter += 1
    return n_i, l_i, m_i

def shore_order(n, l, m):
    r"""Given the indices (n,l,m) of the basis, return the minimum order
    for those indices and their index for modified Merlet's 3D-SHORE.
    
    Parameters
    ----------
    n :  unsigned int
        the index n of the modified shore basis
    l :  unsigned int
        the index l of the modified shore basis
    m :  unsigned int
        the index m of the modified shore basis  

    Returns
    -------
    radial_order : unsigned int
        an even integer that represent the maximal order of the basis
    index : unsigned int
        index of the coefficient correspondig to (n,l,m), start from 0
      
    """
    if l % 2 == 1 or l > n or l < 0 or n < 0  or np.abs(m) > l:
        msg = "The index l must be even and 0 <= l <= n, the index m must be -l <= m <= l."
        raise ValueError(msg)
    else: 
        if n % 2 == 1:
            radial_order = n + 1
        else:
            radial_order = n

        counter_i  = 0

        counter = 0
        for l_i in range(0, radial_order + 1, 2):
            for n_i in range(l_i, int((radial_order + l_i) / 2) + 1):
                for m_i in range(-l_i, l_i + 1):
                    if n == n_i and l == l_i and m == m_i:
                        counter_i = counter
                    counter += 1

    return radial_order, counter_i