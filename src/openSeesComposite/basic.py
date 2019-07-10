import logging

import numpy as np
import openseespy.opensees as ops

#===============================================================================
# Globals
#===============================================================================
__all__ = [
    'areaCircularSector',
    'centroidCircularSector',
    'getClassLogger',
    'nShapesCentroid',
    'patchRect2d',
    'patchHalfCircTube2d',
    'fourFiberSectionGJ',
    'twoFiberSection',
]

logger = logging.getLogger(__name__)


def getClassLogger(name):
    """Get a logger scoped to the requested class.

    Parameters
    ----------
    name : str
        Name of the class to get a logger for.

    Example
    -------
    >>> class ClassWithLogger():
    ...     logger = getClassLogger('ClassWithLogger')
    ...     def some_func(self, msg):
    ...         self.logger.warning(msg)
    ...
    >>> logging.basicConfig(format='%(name)s.%(funcName)s: %(message)s')
    >>> instance = ClassWithLogger()
    >>> instance.some_func('this is a warning')
    __main__.ClassWithLogger.some_func: this is a warning
    """
    return logging.getLogger(__name__ + '.' + name)


#===============================================================================
# Centroids and things
#===============================================================================
def areaCircularSector(d, R):
    theta = 2*np.arccos(np.abs(d)/R)
    area = 0.5*R**2*(theta - np.sin(theta))
    return area


def centroidCircularSector(d, R):
    theta = 2*np.arccos(np.abs(d)/R)
    # NumPy sign gives 0.0 for zeroes, but we want zeroes to be positive. True
    # gets cast to 1.0, and False to 0.0.
    sign = np.sign(d) + (d == 0.0)
    if theta == 0.0:
        centroid = sign*R
    else:
        centroid = sign*4*R*np.sin(0.5*theta)**3/(3*(theta - np.sin(theta)))
    return centroid


def nShapesCentroid(x, y, A):
    """Calculates the centroid of a group of shapes.

    Parameters
    ----------
    x : array_like
        x-coordinates of the centroids of the shapes.
    y : array_like
        y-coordinates of the centroids of the shapes.
    A : array_like
        Areas of the shapes.

    Returns
    -------
    xbar
        x-coordinate of the centroid.
    ybar
        y-coordinate of the centroid.
    A
        Total area of the group.

    Raises
    ------
    ValueError
        if `x`, `y`, and `A` are not the same size.
    """
    x = np.array(x).flatten()
    y = np.array(y).flatten()
    A = np.array(A).flatten()
    if x.size != y.size or x.size != A.size:
        raise ValueError('nShapesCentroid: x, y, A must be the same size')

    xArea = x.dot(A)
    yArea = y.dot(A)
    area = np.sum(A)
    logger.debug(f'xArea={xArea:g}, yArea={yArea:g}, area={area:g}')

    return xArea/area, yArea/area, area


#===============================================================================
# Fiber patches
#===============================================================================
def patchRect2d(matTag, nf, width, startHeight, endHeight):
    """Create a quadrilateral patch suitable for two-dimensional analyses.
    
    All fibers are placed on the z-axis.

    Parameters
    ----------
    matTag : int
        Tag of the uniaxial material to use.
    nf : int
        Number of fibers in the patch.
    width : float
        Width of the patch.
    startHeight : float
        Starting height of the patch.
    endHeight : float
        Ending height of the patch.
    """
    if startHeight >= endHeight:
        logger.warning('Creating fibers with a negative area')
    width = float(width)
    startHeight = float(startHeight)
    endHeight = float(endHeight)
    ops.patch('quad', int(matTag), int(nf), 1, startHeight, -width/2, endHeight,
              -width/2, endHeight, width/2, startHeight, width/2)


def patchHalfCircTube2d(matTag, nf, center, side, D, t):
    """Create a set of fibers to describe half a circular tube.

    Fibers are suitable for two-dimensional analyses since all fibers are placed
    on the Z-axis.

    Parameters
    ----------
    matTag : int
        Tag of the uniaxial material to use.
    nf : int
        Number of fibers along the height of the section.
    center : float
        Y-axis location of the center of the tube.
    side : {'top', 'bottom'}
        Side of the tube to create.
    D : float
        Diameter of the tube.
    t : float
        Thickness of the tube.

    Raises
    ------
    ValueError
        if `side` is not 'top' or 'bottom'
        if `D` is not a positive value
        if `t` is not a positive value
        if `t` is more than 0.5*`D`
    """
    if side.lower() not in ['top', 'bottom']:
        raise ValueError(
            "patchHalfCircTube2d: side should be either 'top' or 'bottom'")
    if D <= 0.0:
        raise ValueError('patchHalfCircTube2d: D should be a positive value')
    if t <= 0.0:
        raise ValueError('patchHalfCircTube2d: t should be a positive value')
    if t > 0.5*D:
        raise ValueError('patchHalfCircTube2d: t is too large relative to D')

    if side.lower() == 'top':
        sign = 1.0
    else:
        sign = -1.0

    ro = D/2
    ri = D/2 - t
    ystep = ro/nf

    for i in range(nf):
        yfar = ro - i*ystep
        ynear = max(ro - (i + 1)*ystep, 0.0)

        x = [0.0, 0.0]
        y = [
            centroidCircularSector(yfar, ro),
            centroidCircularSector(ynear, ro)
        ]
        A = [-areaCircularSector(yfar, ro), areaCircularSector(ynear, ro)]

        if yfar >= ri and ynear >= ri:
            pass
        elif yfar >= ri and ynear < ri:
            x.append(0.0)
            y.append(centroidCircularSector(ynear, ri))
            A.append(-areaCircularSector(ynear, ri))
        else:
            x.append(0.0)
            y.append(centroidCircularSector(yfar, ri))
            A.append(areaCircularSector(yfar, ri))
            x.append(0.0)
            y.append(centroidCircularSector(ynear, ri))
            A.append(-areaCircularSector(ynear, ri))

        _, centroid, area = nShapesCentroid(x, y, A)
        yf = center + sign*centroid
        logger.debug(f'Creating fiber at {yf:g} with area {area:g}')
        ops.fiber(yf, 0.0, area, matTag)


def fourFiberSectionGJ(secTag, matTag, area, Iy, Iz, GJ):
    """Create a fiber section with four fibers with desired section properties.

    Parameters
    ----------
    secTag
        Section tag. If None, defines just the fibers.
    matTag
        Uniaxial material to use.
    A : float
        Desired total cross-sectional area.
    Iy : float
        Desired moment of inertia about the y-axis of the section.
    Iz : float
        Desired moment of inertia about the z-axis of the section.
    GJ : float
        Desired torsional stiffness of the section. Not used if `secTag` is
        None.
    """
    if secTag is not None:
        ops.section('Fiber', int(secTag), '-GJ', float(GJ))
        fourFiberSectionGJ(None, matTag, area, Iy, Iz, GJ)
        return

    fiberA = float(0.25*area)
    fiberZ = float(np.sqrt(Iy/area))
    fiberY = float(np.sqrt(Iz/area))

    ops.fiber(+fiberY, +fiberZ, fiberA, int(matTag))
    ops.fiber(+fiberY, -fiberZ, fiberA, int(matTag))
    ops.fiber(-fiberY, +fiberZ, fiberA, int(matTag))
    ops.fiber(-fiberY, -fiberZ, fiberA, int(matTag))


def twoFiberSection(secTag, matTag, area, I):
    """Create a fiber section with two fibers with desired section properties.

    Parameters
    ----------
    secTag
        Section tag. If None, defines just the fibers.
    matTag
        Uniaxial material to use.
    A : float
        Desired total cross-sectional area.
    I : float
        Desired moment of inertia.
    """
    if secTag is not None:
        ops.section('Fiber', int(secTag))
        twoFiberSection(None, matTag, area, I)
        return

    fiberA = float(0.5*area)
    fiberY = float(np.sqrt(I/area))

    ops.fiber(+fiberY, 0.0, fiberA, int(matTag))
    ops.fiber(-fiberY, 0.0, fiberA, int(matTag))
